"""End-to-end wiring check: the real application factory, a real (SQLite) database, and a scripted model.

It proves the pieces are connected, not that Postgres, Redis or any provider behaves in production.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.api import app as app_module
from mpd_assistant.business.escalations import EscalationService
from mpd_assistant.business.escalations_sql import SqlEscalationRepository
from mpd_assistant.core import config, crypto
from mpd_assistant.core.db import make_engine
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.llm.client import LLMResult
from mpd_assistant.core.models import Base, MemoryRow, Turn, User
from mpd_assistant.ingestion.indexer import index_document
from mpd_assistant.privacy.dsr import DataSubjectService
from mpd_assistant.retrieval.embeddings import HashEmbedder

KNOWLEDGE = "MasterProDev builds custom mobile apps and web platforms for logistics and retail companies."


class ScriptedModel:
    """Stands in for the language model: answers by looking at which agent is asking."""

    def __init__(self, *args, **kwargs):
        pass

    async def complete(self, messages, **kwargs):
        system = messages[0]["content"]
        if "durable facts" in system:
            return LLMResult(json.dumps({"memories": [{"kind": "fact", "text": "runs a logistics company", "importance": 0.8, "confidence": 0.9}]}))
        if "Extract project details" in system:
            return LLMResult(json.dumps({"need": "a fleet app", "timeline": None, "budget": None}))
        return LLMResult("We build custom mobile apps and web platforms.")


class CapturingSender:
    sent = {}

    def __init__(self, channel):
        self.channel = channel

    def send(self, target, code):
        CapturingSender.sent[target] = code


@pytest.fixture
def stack(tmp_path, monkeypatch):
    db_url = f"sqlite:///{(tmp_path / 'e2e.db').as_posix()}"
    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    enc, idx = crypto.generate_key(), crypto.generate_key()
    for key, value in {
        "SECRET_KEY": "e2e-secret-key-value",
        "DATABASE_URL": db_url,
        "REDIS_URL": "redis://127.0.0.1:1",  # nothing listens: development falls back to in-process stores
        "DATA_ENCRYPTION_KEY": enc,
        "BLIND_INDEX_KEY": idx,
        "METRICS_TOKEN": "scrape",
        "HUGGINGFACE_API_KEY": "placeholder",
        "HUGGINGFACE_MODEL": "placeholder/model",
        "ESCALATION_EMAIL": "team@example.com",
        "ENV": "development",
    }.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    monkeypatch.setattr(app_module, "OpenAICompatibleLLM", ScriptedModel)
    monkeypatch.setattr(app_module, "build_embedder", lambda settings: HashEmbedder(64))
    monkeypatch.setattr(app_module, "ConsoleSender", CapturingSender)
    CapturingSender.sent = {}
    import asyncio

    asyncio.run(index_document(engine, app_module.ensure_tenant(engine), "services.txt", KNOWLEDGE, HashEmbedder(64), expected_dim=64))
    yield TestClient(app_module.create()), engine, enc, idx
    config.get_settings.cache_clear()


def chat(client, message, sid=None):
    body = {"message": message}
    if sid:
        body["session_id"] = sid
    return client.post("/v2/chat", json=body).json()


def test_whole_journey_through_the_real_factory(stack):
    client, engine, enc, idx = stack
    assert client.get("/health").json() == {"status": "ok"}

    # 1. A visitor asks a knowledge question: retrieval + model answer with sources, then the repeat is cached.
    first = chat(client, "What mobile apps do you build for logistics?")
    sid = first["session_id"]
    assert "custom mobile apps" in first["reply"] and "services.txt" in first["reply"]
    repeat = chat(client, "What mobile apps do you build for logistics?")
    assert repeat["reply"] == first["reply"]

    # 2. Quotes and bookings are gated until the person is verified.
    assert "verify" in chat(client, "How much would a website cost?", sid)["reply"].lower()

    # 3. Sign up with email and phone, verify both codes, and the same session becomes a verified user.
    r = client.post("/v2/identity/start", json={"session_id": sid, "name": "Ann Lee", "email": "ann@example.com", "phone": "(416) 967-1111"})
    assert r.status_code == 202
    ok = client.post("/v2/identity/verify", json={"session_id": sid, "email_code": CapturingSender.sent["ann@example.com"], "phone_code": CapturingSender.sent["+14169671111"]})
    assert ok.status_code == 200
    with DbSession(engine) as db:
        user = db.scalar(select(User))
        assert "ann@example.com" not in (user.email_enc + user.name_enc + user.phone_enc)
        user_id = user.id

    # 4. Memory is off until the user opts in; then a project description is remembered and listed.
    assert chat(client, "We run a logistics company and want a fleet tracking app", sid)["reply"]
    with DbSession(engine) as db:
        assert db.scalar(select(func.count(MemoryRow.id))) == 0
    assert client.post("/v2/memory/consent", json={"session_id": sid, "enabled": True}).json() == {"memory": "on"}
    chat(client, "We run a logistics company with forty trucks and want a fleet tracking app", sid)
    listed = client.get("/v2/memory", params={"session_id": sid}).json()["memories"]
    assert [m["text"] for m in listed] == ["runs a logistics company"]

    # 5. Asking for a person records an escalation and pauses the assistant; resolving it resumes the chat.
    esc = chat(client, "I want to talk to a real person", sid)
    assert esc["escalated"] and esc["reference"]
    paused = chat(client, "hello? is anyone there", sid)
    assert paused["reference"] == esc["reference"] and "notified" in paused["reply"]
    assert EscalationService(repo=SqlEscalationRepository(engine)).resolve(esc["reference"])
    assert chat(client, "hello", sid)["reply"].startswith("Hello")

    # 6. Turns were stored pseudonymized, and the metrics endpoint is protected.
    with DbSession(engine) as db:
        turns = list(db.scalars(select(Turn)))
    assert len(turns) >= 6 and "ann@example.com" not in " ".join(t.user_text + t.reply_text for t in turns)
    assert client.get("/metrics").status_code == 401
    assert "mpd_turns_total" in client.get("/metrics", headers={"Authorization": "Bearer scrape"}).text

    # 7. Erasing the person removes their rows everywhere the erasure path knows about.
    report = DataSubjectService(engine, MemoryKV(), crypto.FieldCipher(enc), idx).erase(user_id)
    assert report.complete and report.deleted["users"] == 1 and report.deleted["memories"] == 1
    with DbSession(engine) as db:
        assert db.scalar(select(func.count(User.id))) == 0
        assert db.scalar(select(func.count(MemoryRow.id))) == 0
        # The person's own conversation is gone; the one turn left is the anonymous repeat visit, never linked to them.
        assert db.scalar(select(func.count(Turn.id))) == 1


def test_production_factory_refuses_placeholder_secrets(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "change-me")
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="production configuration incomplete"):
        app_module.create()
    config.get_settings.cache_clear()
