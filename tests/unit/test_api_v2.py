import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.api.main import Services, create_app
from mpd_assistant.core import crypto
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.service import IdentityService, MemoryUserRepository
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.routing.intents import Agent
from mpd_assistant.sessions.service import MemorySessionRepository, SessionService


class CaptureSender:
    def __init__(self):
        self.codes = {}

    def send(self, target, code):
        self.codes[target] = code


@pytest.fixture
def env():
    key = crypto.generate_key()
    email_s, sms_s = CaptureSender(), CaptureSender()

    async def quote_agent(state):
        return {"response": "Here is your draft quote."}

    vault = PiiVault(crypto.FieldCipher(key), MemoryVaultStore())
    graph = build_graph({Agent.QUOTE: quote_agent}, checkpointer=MemorySaver())
    identity = IdentityService(
        crypto.FieldCipher(key), key, MemoryUserRepository(), OtpService("e"), OtpService("s"), email_s, sms_s
    )
    app = create_app(Services(ChatService(graph, vault), SessionService(MemorySessionRepository()), identity))
    return TestClient(app), email_s, sms_s


def test_health_and_security_headers(env):
    client, _, _ = env
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff" and "frame-ancestors" in r.headers["Content-Security-Policy"]
    assert client.get("/docs").status_code == 404


def test_visitor_is_gated_then_verified_flow_unlocks_agent(env):
    client, email_s, sms_s = env
    first = client.post("/v2/chat", json={"message": "I need a quote"}).json()
    sid = first["session_id"]
    assert "verify" in first["reply"].lower()

    r = client.post("/v2/identity/start", json={"session_id": sid, "name": "Ann Lee", "email": "Ann@Example.com", "phone": "(416) 967-1111"})
    assert r.status_code == 202

    bad = client.post("/v2/identity/verify", json={"session_id": sid, "email_code": "000000", "phone_code": "000000"})
    assert bad.status_code == 400

    ok = client.post(
        "/v2/identity/verify",
        json={"session_id": sid, "email_code": email_s.codes["ann@example.com"], "phone_code": sms_s.codes["+14169671111"]},
    )
    assert ok.status_code == 200

    second = client.post("/v2/chat", json={"message": "I need a quote", "session_id": sid}).json()
    assert second["reply"] == "Here is your draft quote."


def test_identity_input_validation_and_unknown_session(env):
    client, _, _ = env
    sid = client.post("/v2/chat", json={"message": "hello"}).json()["session_id"]
    bad = client.post("/v2/identity/start", json={"session_id": sid, "name": "A", "email": "nope", "phone": "123"})
    assert bad.status_code == 422
    unknown = client.post("/v2/identity/start", json={"session_id": "zzz", "name": "A", "email": "a@b.co", "phone": "4169671111"})
    assert unknown.status_code == 401


def test_message_length_limit(env):
    client, _, _ = env
    assert client.post("/v2/chat", json={"message": "x" * 5000}).status_code == 422
    assert client.post("/v2/chat", json={"message": ""}).status_code == 422
