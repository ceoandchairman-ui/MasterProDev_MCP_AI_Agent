import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.pool import StaticPool

from mpd_assistant.api.main import Services, create_app
from mpd_assistant.core import crypto
from mpd_assistant.core.db import ensure_tenant
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.models import Base, User
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.account import AccountService
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.service import IdentityService, VerifiedUser
from mpd_assistant.identity.sql import SqlUserRepository
from mpd_assistant.privacy.dsr import DataSubjectService
from mpd_assistant.privacy.kv_store import KvVaultStore
from mpd_assistant.privacy.vault import PiiVault
from mpd_assistant.sessions.service import SessionService
from mpd_assistant.sessions.sql import SqlSessionRepository


class Capture:
    def __init__(self):
        self.codes = {}

    def send(self, target, code):
        self.codes[target] = code


@pytest.fixture
def world():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    tenant = ensure_tenant(engine)
    kv = MemoryKV()
    enc, idx = crypto.generate_key(), crypto.generate_key()
    cipher = crypto.FieldCipher(enc)
    users = SqlUserRepository(engine, tenant)

    def add(uid, name, email, phone):
        users.save(VerifiedUser(uid, cipher.encrypt(name), cipher.encrypt(email), crypto.blind_index(idx, email),
                                cipher.encrypt(phone), crypto.blind_index(idx, phone), None))

    add("u1", "Ann Lee", "ann@example.com", "+14169671111")
    add("u2", "Bob Roy", "bob@example.com", "+14165550100")
    email_s, sms_s, changes = Capture(), Capture(), []
    account = AccountService(
        users, cipher, idx, kv, OtpService("a", store=kv, namespace="stepup"), OtpService("b", store=kv, namespace="em"),
        OtpService("c", store=kv, namespace="sm"), email_s, sms_s, notify_change=lambda kind, old: changes.append((kind, old)),
    )
    sessions = SessionService(SqlSessionRepository(engine, tenant))
    vault = PiiVault(cipher, KvVaultStore(kv))
    chat = ChatService(build_graph({}, checkpointer=MemorySaver()), vault)
    identity = IdentityService(cipher, idx, users, OtpService("e"), OtpService("s"), email_s, sms_s, kv=kv)
    app = create_app(Services(chat, sessions, identity, kv=kv, account=account, dsr=DataSubjectService(engine, kv, cipher, idx)))
    session = sessions.create("u1", True)
    return TestClient(app), session, email_s, sms_s, changes, engine, users, cipher, idx, sessions


def stepped_up(client, session, email_s):
    assert client.post("/v2/account/stepup/start", json={"session_id": session.id}).status_code == 202
    code = email_s.codes["ann@example.com"]
    return client.post("/v2/account/stepup/verify", json={"session_id": session.id, "code": code})


def test_sensitive_actions_need_a_recent_code(world):
    client, session, email_s, *_ = world
    for call in (
        lambda: client.get("/v2/account/export", params={"session_id": session.id}),
        lambda: client.post("/v2/account/delete", json={"session_id": session.id, "confirm": "DELETE"}),
        lambda: client.post("/v2/account/contact/start", json={"session_id": session.id, "kind": "email", "value": "new@example.com"}),
    ):
        r = call()
        assert r.status_code == 403 and r.json()["detail"] == "step_up_required"
    assert stepped_up(client, session, email_s).status_code == 200
    assert client.get("/v2/account/export", params={"session_id": session.id}).status_code == 200


def test_wrong_step_up_code_is_rejected_and_does_not_unlock_anything(world):
    client, session, email_s, *_ = world
    client.post("/v2/account/stepup/start", json={"session_id": session.id})
    bad = client.post("/v2/account/stepup/verify", json={"session_id": session.id, "code": "000000"})
    assert bad.status_code == 400
    assert client.get("/v2/account/export", params={"session_id": session.id}).status_code == 403


def test_step_up_is_tied_to_one_session(world):
    client, session, email_s, _, _, _, _, _, _, sessions = world
    stepped_up(client, session, email_s)
    other_device = sessions.create("u1", True)
    assert client.get("/v2/account/export", params={"session_id": other_device.id}).status_code == 403


def test_name_can_be_changed_without_step_up_but_is_validated(world):
    client, session, *_ = world
    assert client.patch("/v2/account/profile", json={"session_id": session.id, "name": "Ann M. Lee"}).status_code == 200
    assert client.patch("/v2/account/profile", json={"session_id": session.id, "name": "<script>"}).status_code == 422


def test_changing_email_requires_a_code_sent_to_the_new_address_and_alerts_the_old_one(world):
    client, session, email_s, _, changes, engine, users, cipher, idx, _ = world
    stepped_up(client, session, email_s)
    assert client.post("/v2/account/contact/start", json={"session_id": session.id, "kind": "email", "value": "Ann.New@Example.com"}).status_code == 202
    assert client.post("/v2/account/contact/verify", json={"session_id": session.id, "code": "000000"}).status_code == 400
    ok = client.post("/v2/account/contact/verify", json={"session_id": session.id, "code": email_s.codes["ann.new@example.com"]})
    assert ok.status_code == 200 and changes == [("email", "ann@example.com")]
    assert users.find_by_email_index(crypto.blind_index(idx, "ann.new@example.com")).id == "u1"
    assert users.find_by_email_index(crypto.blind_index(idx, "ann@example.com")) is None


def test_taking_over_another_users_email_fails_like_a_wrong_code(world):
    client, session, email_s, _, changes, _, users, _, idx, _ = world
    stepped_up(client, session, email_s)
    client.post("/v2/account/contact/start", json={"session_id": session.id, "kind": "email", "value": "bob@example.com"})
    r = client.post("/v2/account/contact/verify", json={"session_id": session.id, "code": email_s.codes["bob@example.com"]})
    assert r.status_code == 400 and changes == []
    assert users.find_by_email_index(crypto.blind_index(idx, "bob@example.com")).id == "u2"


def test_changing_phone_updates_the_lookup_index(world):
    client, session, email_s, sms_s, changes, _, users, _, idx, _ = world
    stepped_up(client, session, email_s)
    client.post("/v2/account/contact/start", json={"session_id": session.id, "kind": "phone", "value": "(416) 967-2222"})
    r = client.post("/v2/account/contact/verify", json={"session_id": session.id, "code": sms_s.codes["+14169672222"]})
    assert r.status_code == 200 and changes == [("phone", "+14169671111")]
    assert users.find_by_phone_index(crypto.blind_index(idx, "+14169672222")).id == "u1"


def test_invalid_contact_values_are_rejected_before_any_code_is_sent(world):
    client, session, email_s, sms_s, *_ = world
    stepped_up(client, session, email_s)
    assert client.post("/v2/account/contact/start", json={"session_id": session.id, "kind": "email", "value": "nope"}).status_code == 422
    assert client.post("/v2/account/contact/start", json={"session_id": session.id, "kind": "phone", "value": "123"}).status_code == 422
    assert list(sms_s.codes) == []


def test_export_returns_only_the_requesters_data(world):
    client, session, email_s, *_ = world
    stepped_up(client, session, email_s)
    out = client.get("/v2/account/export", params={"session_id": session.id}).json()
    assert out["profile"]["email"] == "ann@example.com" and "bob@example.com" not in str(out)


def test_deletion_needs_the_confirmation_word_then_erases_and_signs_out(world):
    client, session, email_s, _, _, engine, _, _, _, sessions = world
    stepped_up(client, session, email_s)
    assert client.post("/v2/account/delete", json={"session_id": session.id, "confirm": "yes"}).status_code == 422
    assert client.post("/v2/account/delete", json={"session_id": session.id, "confirm": "DELETE"}).json() == {"status": "deleted"}
    with DbSession(engine) as db:
        assert [u.id for u in db.scalars(select(User))] == ["u2"]
        assert db.scalar(select(func.count(User.id))) == 1
    assert sessions.resume(session.id) is None


def test_google_connection_also_requires_a_recent_code(world):
    client, session, email_s, *_ = world
    assert client.get("/v2/integrations/google/start", params={"session_id": session.id}).status_code == 403
