"""Two service instances sharing one database and one key-value store behave like two replicas."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.pool import StaticPool

from mpd_assistant.business.leads_sql import SqlLeadRepository
from mpd_assistant.core import crypto
from mpd_assistant.core.db import ensure_tenant
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.models import Base, FunnelEvent, Lead
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.service import IdentityService
from mpd_assistant.identity.sql import SqlUserRepository
from mpd_assistant.privacy.kv_store import KvVaultStore
from mpd_assistant.privacy.vault import PiiVault
from mpd_assistant.sessions.service import SessionService
from mpd_assistant.sessions.sql import SqlSessionRepository


@pytest.fixture
def shared():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, ensure_tenant(engine), MemoryKV(), crypto.generate_key(), crypto.generate_key()


class Capture:
    def __init__(self):
        self.codes = {}

    def send(self, target, code):
        self.codes[target] = code


def replica(shared, email_sender=None, sms_sender=None):
    engine, tenant, kv, enc_key, idx_key = shared
    cipher = crypto.FieldCipher(enc_key)
    users = SqlUserRepository(engine, tenant)
    identity = IdentityService(
        cipher, idx_key, users, OtpService("e", store=kv, namespace="e"), OtpService("s", store=kv, namespace="s"),
        email_sender or Capture(), sms_sender or Capture(), kv=kv,
    )
    return {
        "sessions": SessionService(SqlSessionRepository(engine, tenant)),
        "vault": PiiVault(cipher, KvVaultStore(kv)),
        "identity": identity,
        "users": users,
        "leads": SqlLeadRepository(engine, tenant),
    }


def test_session_created_on_one_replica_resumes_on_another(shared):
    a, b = replica(shared), replica(shared)
    s = a["sessions"].create()
    resumed = b["sessions"].resume(s.id)
    assert resumed and resumed.thread_id == s.thread_id
    b["sessions"].revoke(s.id)
    assert a["sessions"].resume(s.id) is None  # revocation is visible everywhere


def test_vault_tokens_are_shared_between_replicas(shared):
    a, b = replica(shared), replica(shared)
    tokenized = a["vault"].tokenize("t1", "mail ann@example.com")
    assert tokenized == "mail <EMAIL_1>"
    assert b["vault"].detokenize("t1", "<EMAIL_1>") == "ann@example.com"
    assert b["vault"].tokenize("t1", "ann@example.com") == "<EMAIL_1>"


async def test_signup_started_on_one_replica_finishes_on_another(shared):
    email_s, sms_s = Capture(), Capture()
    a, b = replica(shared, email_s, sms_s), replica(shared)
    session = a["sessions"].create()
    await a["identity"].start(session.id, "Ann Lee", "ann@example.com", "(416) 967-1111")
    user = b["identity"].verify(session.id, email_s.codes["ann@example.com"], sms_s.codes["+14169671111"])
    assert user is not None
    assert a["users"].find_by_id(user.id).id == user.id
    assert a["users"].find_by_phone_index(user.phone_index).id == user.id


async def test_pending_signup_and_codes_are_not_stored_in_clear(shared):
    _, _, kv, _, _ = shared
    a = replica(shared)
    session = a["sessions"].create()
    await a["identity"].start(session.id, "Ann Lee", "ann@example.com", "(416) 967-1111")
    dump = str(kv._data)
    for secret in ("ann@example.com", "Ann Lee", "+14169671111"):
        assert secret not in dump


def test_users_are_encrypted_in_the_database(shared):
    engine = shared[0]
    import asyncio

    email_s, sms_s = Capture(), Capture()
    a = replica(shared, email_s, sms_s)
    s = a["sessions"].create()
    asyncio.run(a["identity"].start(s.id, "Ann Lee", "ann@example.com", "(416) 967-1111"))
    a["identity"].verify(s.id, email_s.codes["ann@example.com"], sms_s.codes["+14169671111"])
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("select name_enc, email_enc, email_index, phone_enc, phone_index from users").fetchall()
    assert rows and all("ann@example.com" not in str(v) and "+1416" not in str(v) for r in rows for v in r)


def test_lead_upsert_records_stage_changes_and_skips_anonymous(shared):
    engine = shared[0]
    leads = replica(shared)["leads"]
    leads.upsert(None, "engaged", {})
    with DbSession(engine) as db:
        assert db.scalar(select(Lead)) is None
        from mpd_assistant.core.models import Tenant, User

        tenant = db.scalar(select(Tenant))
        db.add(User(id="u1", tenant_id=tenant.id, name_enc="x", email_enc="x", email_index="i1", phone_enc="x", phone_index="p1"))
        db.commit()
    leads.upsert("u1", "engaged", {"need": "app"})
    leads.upsert("u1", "engaged", {"need": "app", "timeline": "March"})
    leads.upsert("u1", "qualified", {"need": "app", "timeline": "March", "budget": "40k"})
    with DbSession(engine) as db:
        lead = db.scalar(select(Lead))
        events = [(e.from_stage, e.to_stage) for e in db.scalars(select(FunnelEvent).order_by(FunnelEvent.created_at))]
    assert lead.stage == "qualified" and lead.budget_range == "40k"
    assert events == [("none", "engaged"), ("engaged", "qualified")]
