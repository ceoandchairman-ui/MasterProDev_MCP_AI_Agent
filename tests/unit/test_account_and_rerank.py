import json

import httpx
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.api.main import Services, create_app
from mpd_assistant.core import crypto
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.service import IdentityService, MemoryUserRepository
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.retrieval.hybrid import Hit
from mpd_assistant.retrieval.rerank import HostedReranker
from mpd_assistant.sessions.service import MemorySessionRepository, SessionService


def account_app():
    cipher = crypto.FieldCipher(crypto.generate_key())
    sessions = SessionService(MemorySessionRepository())
    chat = ChatService(build_graph({}, checkpointer=MemorySaver()), PiiVault(cipher, MemoryVaultStore()))
    identity = IdentityService(cipher, crypto.generate_key(), MemoryUserRepository(), OtpService("e"), OtpService("s"), None, None, kv=MemoryKV())
    return TestClient(create_app(Services(chat, sessions, identity))), sessions


def test_user_sees_only_their_active_sessions_with_short_ids():
    client, sessions = account_app()
    mine = sessions.create("u1", True)
    sessions.create("u1", True)
    sessions.create("u2", True)
    sessions.revoke(sessions.create("u1", True).id)
    rows = client.get("/v2/account/sessions", params={"session_id": mine.id}).json()["sessions"]
    assert len(rows) == 2 and all(len(r["id"]) == 6 for r in rows)
    assert [r["current"] for r in rows].count(True) == 1


def test_revoking_other_devices_keeps_the_current_one():
    client, sessions = account_app()
    mine, other = sessions.create("u1", True), sessions.create("u1", True)
    assert client.post("/v2/account/sessions/revoke", json={"session_id": mine.id}).json() == {"revoked": 1}
    assert sessions.resume(other.id) is None and sessions.resume(mine.id) is not None


def test_revoking_a_single_device_and_unknown_targets():
    client, sessions = account_app()
    mine, other = sessions.create("u1", True), sessions.create("u1", True)
    assert client.post("/v2/account/sessions/revoke", json={"session_id": mine.id, "target_id": other.id[-6:]}).json() == {"revoked": 1}
    assert client.post("/v2/account/sessions/revoke", json={"session_id": mine.id, "target_id": "zzzzzz"}).status_code == 404
    assert client.post("/v2/account/sessions/revoke", json={"session_id": mine.id, "target_id": mine.id[-6:]}).status_code == 404  # not itself


def test_visitors_cannot_manage_sessions():
    client, sessions = account_app()
    guest = sessions.create()
    assert client.get("/v2/account/sessions", params={"session_id": guest.id}).status_code == 403
    assert client.post("/v2/account/sessions/revoke", json={"session_id": guest.id}).status_code == 403


def hits():
    return [Hit("a", "alpha text", "a.txt", 0.5), Hit("b", "beta text", "b.txt", 0.4), Hit("c", "gamma text", "c.txt", 0.3)]


async def test_reranker_reorders_and_replaces_scores():
    def handler(request):
        body = json.loads(request.content)
        assert body["documents"] == ["alpha text", "beta text", "gamma text"] and request.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"results": [{"index": 2, "relevance_score": 0.91}, {"index": 0, "relevance_score": 0.4}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = await HostedReranker("https://rerank.example/v1", "k", "m", client=client).rerank("q", hits())
    assert [h.doc_id for h in out] == ["c", "a"] and out[0].score == 0.91


async def test_reranker_fails_soft_to_the_original_order():
    for response in (httpx.Response(500), httpx.Response(200, json={"unexpected": True}), httpx.Response(200, text="not json")):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r, resp=response: resp))
        out = await HostedReranker("https://rerank.example/v1", "k", "m", client=client).rerank("q", hits())
        assert [h.doc_id for h in out] == ["a", "b", "c"]


async def test_reranker_skips_the_call_for_single_results():
    def handler(request):
        raise AssertionError("no call expected")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    single = [Hit("a", "only", "a.txt", 0.5)]
    assert await HostedReranker("https://x/v1", "k", "m", client=client).rerank("q", single) == single
