import json

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.pool import StaticPool

from mpd_assistant.agents.comms_scheduling.agent import make_comms
from mpd_assistant.core import crypto
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.llm.client import FakeLLM
from mpd_assistant.core.models import Base, OAuthToken, Tenant, User
from mpd_assistant.integrations.context import current_token, reset_token, set_token
from mpd_assistant.integrations.google_oauth import GoogleOAuth, NotConfigured, OAuthError
from mpd_assistant.routing.intents import Agent
from mpd_assistant.tools.executor import ToolContext, ToolExecutor, http_backend
from mpd_assistant.tools.registry import Role, default_registry


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with DbSession(engine) as s:
        t = Tenant(name="t")
        s.add(t)
        s.flush()
        s.add(User(id="u1", tenant_id=t.id, name_enc="x", email_enc="x", email_index="i", phone_enc="x", phone_index="p"))
        s.commit()
    return engine


def google(engine, http, kv=None, cipher=None, configured=True):
    return GoogleOAuth(
        engine,
        kv or MemoryKV(),
        cipher or crypto.FieldCipher(crypto.generate_key()),
        "client-id" if configured else None,
        "client-secret" if configured else None,
        "https://api.example.com/v2/integrations/google/callback" if configured else None,
        http=http,
    )


def token_server(refresh="REFRESH-1", access="ACCESS-1", fail=False, calls=None):
    def handler(request):
        form = dict(p.split("=", 1) for p in request.content.decode().split("&"))
        if calls is not None:
            calls.append(form)
        if fail:
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "secret-detail"})
        body = {"access_token": access, "expires_in": 3600}
        if form.get("grant_type") == "authorization_code":
            body["refresh_token"] = refresh
        return httpx.Response(200, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_authorize_url_needs_configuration(db):
    with pytest.raises(NotConfigured):
        google(db, None, configured=False).authorize_url("u1")
    url = google(db, None).authorize_url("u1")
    assert url.startswith("https://accounts.google.com/") and "access_type=offline" in url and "state=" in url


async def test_connect_stores_encrypted_refresh_token_and_state_is_single_use(db):
    kv = MemoryKV()
    cipher = crypto.FieldCipher(crypto.generate_key())
    svc = google(db, token_server(), kv, cipher)
    url = svc.authorize_url("u1")
    state = url.split("state=")[1].split("&")[0]
    assert await svc.complete(state, "code-123") == "u1"
    with DbSession(db) as s:
        row = s.scalar(select(OAuthToken))
    assert row is not None and "REFRESH-1" not in row.refresh_enc and cipher.decrypt(row.refresh_enc) == "REFRESH-1"
    with pytest.raises(OAuthError):
        await svc.complete(state, "code-123")  # replay


async def test_bad_or_forged_state_is_rejected(db):
    svc = google(db, token_server())
    with pytest.raises(OAuthError):
        await svc.complete("forged-state", "code")
    assert not svc.is_connected("u1")


async def test_access_token_is_cached_then_refreshed(db):
    kv = MemoryKV()
    calls = []
    svc = google(db, token_server(calls=calls), kv)
    state = svc.authorize_url("u1").split("state=")[1].split("&")[0]
    await svc.complete(state, "code")
    assert await svc.access_token("u1") == "ACCESS-1"  # cached from the exchange
    kv.delete("oauth-access:google:u1")
    assert await svc.access_token("u1") == "ACCESS-1"
    assert calls[-1]["grant_type"] == "refresh_token"


async def test_revoked_grant_disconnects_and_hides_error_detail(db):
    kv = MemoryKV()
    cipher = crypto.FieldCipher(crypto.generate_key())
    good = google(db, token_server(), kv, cipher)
    state = good.authorize_url("u1").split("state=")[1].split("&")[0]
    await good.complete(state, "code")
    kv.delete("oauth-access:google:u1")
    revoked = google(db, token_server(fail=True), kv, cipher)
    assert await revoked.access_token("u1") is None
    assert not revoked.is_connected("u1")


async def test_never_connected_user_and_unconfigured_return_none(db):
    assert await google(db, token_server()).access_token("u1") is None
    assert await google(db, None, configured=False).access_token("u1") is None


async def test_disconnect_removes_grant_and_cache(db):
    kv = MemoryKV()
    svc = google(db, token_server(), kv)
    state = svc.authorize_url("u1").split("state=")[1].split("&")[0]
    await svc.complete(state, "code")
    assert svc.disconnect("u1") is True and svc.disconnect("u1") is False
    assert kv.get("oauth-access:google:u1") is None and await svc.access_token("u1") is None


async def test_access_token_reaches_google_servers_as_header_only():
    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "success"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    routes = {"get_calendar_events": ("http://cal:8001", "get_events")}
    executor = ToolExecutor(default_registry(), http_backend(routes, "svc", client))
    ctx = ToolContext(Agent.COMMS_SCHEDULING, Role.VERIFIED, google_access_token="USER-TOKEN")
    outcome = await executor.run("get_calendar_events", {"days": 2}, ctx)
    assert outcome.status == "ok"
    assert seen["headers"]["x-google-access-token"] == "USER-TOKEN"
    assert "USER-TOKEN" not in json.dumps(seen["body"])  # never in arguments, so never in logs or traces
    assert current_token() is None  # the context is cleared after the call


async def test_comms_asks_user_to_connect_when_no_grant():
    async def provider(user_id):
        return None

    registry = default_registry()
    executor = ToolExecutor(registry, lambda t, a: None)
    plan = json.dumps({"steps": [{"tool": "get_calendar_events", "args": {"days": 2}}]})
    run = make_comms(FakeLLM([plan]), executor, registry, token_provider=provider)
    out = await run({"messages": [{"role": "user", "content": "what is on my calendar"}], "language": "en", "user_id": "u1", "session_id": "s"})
    assert "connect" in out["response"].lower()


def test_context_token_resets_after_call():
    marker = set_token("abc")
    assert current_token() == "abc"
    reset_token(marker)
    assert current_token() is None
