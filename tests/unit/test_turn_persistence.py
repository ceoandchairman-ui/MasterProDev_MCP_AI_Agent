from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.pool import StaticPool

from mpd_assistant.api.main import Services, create_app
from mpd_assistant.core import crypto
from mpd_assistant.core.db import ensure_tenant
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.models import Base, Turn
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.service import IdentityService
from mpd_assistant.identity.sql import SqlUserRepository
from mpd_assistant.privacy.kv_store import KvVaultStore
from mpd_assistant.privacy.vault import PiiVault
from mpd_assistant.sessions.service import SessionService
from mpd_assistant.sessions.sql import SqlSessionRepository
from mpd_assistant.sessions.turns import SqlTurnRecorder


def test_turns_are_stored_tokenized_and_exportable():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    tenant = ensure_tenant(engine)
    kv = MemoryKV()
    enc, idx = crypto.generate_key(), crypto.generate_key()
    cipher = crypto.FieldCipher(enc)
    vault = PiiVault(cipher, KvVaultStore(kv))
    chat = ChatService(build_graph({}, checkpointer=MemorySaver()), vault)
    sessions = SessionService(SqlSessionRepository(engine, tenant))
    users = SqlUserRepository(engine, tenant)
    identity = IdentityService(cipher, idx, users, OtpService("e"), OtpService("s"), None, None, kv=kv)
    app = create_app(Services(chat, sessions, identity, kv=kv, turns=SqlTurnRecorder(engine)))
    client = TestClient(app)

    r = client.post("/v2/chat", json={"message": "hello, my email is ann@example.com"}).json()
    client.post("/v2/chat", json={"message": "what services do you offer?", "session_id": r["session_id"]})

    with DbSession(engine) as db:
        rows = list(db.scalars(select(Turn).order_by(Turn.created_at)))
    assert len(rows) == 2
    stored = " ".join(t.user_text + t.reply_text for t in rows)
    assert "ann@example.com" not in stored and "<EMAIL_1>" in rows[0].user_text
    assert rows[1].intent == "faq" and rows[1].agent == "concierge"
