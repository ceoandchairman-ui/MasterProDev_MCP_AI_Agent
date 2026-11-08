import asyncio
import json

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.api import main as api
from mpd_assistant.api.main import Services, create_app
from mpd_assistant.core import crypto
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.service import IdentityService, MemoryUserRepository
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.routing.intents import Agent
from mpd_assistant.sessions.service import MemorySessionRepository, SessionService


def client(runners=None):
    cipher = crypto.FieldCipher(crypto.generate_key())
    chat = ChatService(build_graph(runners or {}, checkpointer=MemorySaver()), PiiVault(cipher, MemoryVaultStore()))
    identity = IdentityService(cipher, crypto.generate_key(), MemoryUserRepository(), OtpService("e"), OtpService("s"), None, None, kv=MemoryKV())
    return TestClient(create_app(Services(chat, SessionService(MemorySessionRepository()), identity)))


def parse(body: str):
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def test_stream_emits_thinking_chunks_and_done_in_order():
    async def long_answer(state):
        return {"response": "First point. Second point! Third point?"}

    c = client({Agent.CONCIERGE: long_answer})
    r = c.post("/v2/chat/stream", json={"message": "tell me what services you offer in detail please"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse(r.text)
    assert events[0] == {"type": "thinking"} and events[-1]["type"] == "done" and events[-1]["session_id"]
    assert [e["text"] for e in events if e["type"] == "chunk"] == ["First point.", "Second point!", "Third point?"]


def test_stream_reply_matches_the_non_streaming_reply_and_keeps_the_session():
    c = client()
    first = parse(c.post("/v2/chat/stream", json={"message": "hello"}).text)
    sid = first[-1]["session_id"]
    plain = c.post("/v2/chat", json={"message": "hello", "session_id": sid}).json()
    assert " ".join(e["text"] for e in first if e["type"] == "chunk") == plain["reply"] and plain["session_id"] == sid


def test_stream_reports_failures_as_a_safe_error_event():
    async def broken_chat(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    c = client()
    original = ChatService.chat
    ChatService.chat = broken_chat
    try:
        events = parse(c.post("/v2/chat/stream", json={"message": "hello"}).text)
    finally:
        ChatService.chat = original
    assert events[0]["type"] == "thinking" and events[-1]["type"] == "error"
    assert "secret internal detail" not in json.dumps(events)


def test_keepalive_comments_are_sent_while_waiting(monkeypatch):
    monkeypatch.setattr(api, "KEEPALIVE_SECONDS", 0.05)

    async def slow(state):
        await asyncio.sleep(0.3)
        return {"response": "Done waiting."}

    c = client({Agent.CONCIERGE: slow})
    body = c.post("/v2/chat/stream", json={"message": "tell me what services you offer in detail please"}).text
    assert ": keepalive" in body and parse(body)[-1]["type"] == "done"


def test_sentence_splitter_handles_edge_cases():
    assert api._sentences("One.   Two") == ["One.", "Two"]
    assert api._sentences("No punctuation here") == ["No punctuation here"]
    assert api._sentences("  ") == ["  "]
