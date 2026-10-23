import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.pool import StaticPool

from mpd_assistant.core import crypto
from mpd_assistant.core.db import ensure_tenant
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.models import AuditLog, Base, FunnelEvent, Lead, Turn, User
from mpd_assistant.core.models import Session as SessionRow
from mpd_assistant.identity.service import VerifiedUser
from mpd_assistant.identity.sql import SqlUserRepository
from mpd_assistant.memory.long_term.store import Candidate, MemoryStore
from mpd_assistant.privacy.dsr import DataSubjectService


@pytest.fixture
def world():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    tenant = ensure_tenant(engine)
    enc, idx = crypto.generate_key(), crypto.generate_key()
    cipher = crypto.FieldCipher(enc)
    users = SqlUserRepository(engine, tenant)
    users.save(VerifiedUser("u1", cipher.encrypt("Ann Lee"), cipher.encrypt("ann@example.com"), crypto.blind_index(idx, "ann@example.com"),
                            cipher.encrypt("+14169671111"), crypto.blind_index(idx, "+14169671111"), None))
    users.save(VerifiedUser("u2", cipher.encrypt("Bob"), cipher.encrypt("bob@example.com"), crypto.blind_index(idx, "bob@example.com"),
                            cipher.encrypt("+14165550100"), crypto.blind_index(idx, "+14165550100"), None))
    with DbSession(engine) as db:
        db.add(SessionRow(id="s1", thread_id="t1", tenant_id=tenant, user_id="u1"))
        db.add(SessionRow(id="s2", thread_id="t2", tenant_id=tenant, user_id="u2"))
        db.flush()
        db.add(Turn(session_id="s1", user_text="<EMAIL_1>", reply_text="ok"))
        db.add(Turn(session_id="s2", user_text="hi", reply_text="hello"))
        db.add(Lead(id="l1", tenant_id=tenant, user_id="u1", stage="engaged"))
        db.flush()
        db.add(FunnelEvent(lead_id="l1", from_stage="none", to_stage="engaged"))
        db.commit()
    kv = MemoryKV()
    kv.set("vault:s1", {"<EMAIL_1>": "x"}, 60)
    kv.set("vault:s2", {"<EMAIL_1>": "y"}, 60)
    kv.set("optout:sms:+14169671111", True, 60)
    memory = MemoryStore()
    memory.write("u1", Candidate("fact", "works in logistics"), True)
    memory.write("u2", Candidate("fact", "uses postgres"), True)
    return engine, kv, cipher, idx, memory


def test_export_contains_only_the_requesters_data(world):
    engine, kv, cipher, idx, memory = world
    dsr = DataSubjectService(engine, kv, cipher, idx, memory)
    out = dsr.export("u1")
    assert out["profile"] == {"name": "Ann Lee", "email": "ann@example.com", "phone": "+14169671111", "created_at": out["profile"]["created_at"], "memory_consent": False}
    assert [t["session_id"] for t in out["conversation"]] == ["s1"]
    assert [m["text"] for m in out["memories"]] == ["works in logistics"]
    assert "bob" not in str(out).lower()


def test_erase_removes_every_store_for_that_person_only(world):
    engine, kv, cipher, idx, memory = world
    dsr = DataSubjectService(engine, kv, cipher, idx, memory)
    report = dsr.erase("u1")
    assert report.complete and report.memories_removed == 1
    assert report.deleted["users"] == 1 and report.deleted["turns"] == 1 and report.deleted["leads"] == 1 and report.deleted["funnel_events"] == 1
    assert kv.get("vault:s1") is None and kv.get("optout:sms:+14169671111") is None
    assert kv.get("vault:s2") is not None  # another person's data untouched
    with DbSession(engine) as db:
        assert db.scalar(select(User).where(User.id == "u1")) is None
        assert db.scalar(select(User).where(User.id == "u2")) is not None
        assert db.scalar(select(Turn).where(Turn.session_id == "s2")) is not None
        assert db.scalar(select(FunnelEvent)) is None
        audit = db.scalars(select(AuditLog)).all()
    assert len(audit) == 1 and "ann@example.com" not in str(audit[0].detail) and "u1" not in audit[0].target


def test_erase_is_idempotent_and_export_after_erase_is_empty(world):
    engine, kv, cipher, idx, memory = world
    dsr = DataSubjectService(engine, kv, cipher, idx, memory)
    dsr.erase("u1")
    second = dsr.erase("u1")
    assert second.complete and second.deleted.get("users", 0) == 0
    assert dsr.export("u1") == {"user_id": "u1", "found": False}
