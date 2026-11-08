"""Event loop hygiene: blocking database and cache calls stay off the loop, handlers that never await run on the thread
pool, and Redis and Postgres calls are bounded in time."""

import asyncio
import inspect
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from mpd_assistant.api import app as app_module
from mpd_assistant.api.main import Services, create_app
from mpd_assistant.core import config, crypto
from mpd_assistant.core.db import make_engine
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.graph.service import ChatResult
from mpd_assistant.memory.long_term.store import MemoryStore
from mpd_assistant.memory.pipeline import MemoryWiring

MAIN_THREAD = threading.get_ident()


# --- the loop stays responsive while the database is slow ----------------------------------
class SlowSessions:
    """A session store whose every call blocks its thread for 0.2 seconds, like a slow Postgres."""

    def __init__(self):
        self.threads = []

    def _slow(self):
        self.threads.append(threading.get_ident())
        time.sleep(0.2)

    def resume(self, session_id):
        self._slow()
        return SimpleNamespace(id="row1", thread_id="t1", verified=False, user_id=None)

    def create(self):
        self._slow()
        return SimpleNamespace(id="row1", thread_id="t1", verified=False, user_id=None)


class SlowKV(MemoryKV):
    def incr(self, key, ttl_seconds):
        time.sleep(0.2)
        return super().incr(key, ttl_seconds)


class Chat:
    async def chat(self, thread_id, message, **kw):
        return ChatResult("Hello", False, None, [], safe_user_text=message)


async def test_a_slow_database_does_not_freeze_the_event_loop():
    sessions = SlowSessions()
    app = create_app(Services(chat=Chat(), sessions=sessions, identity=None, kv=SlowKV(), edge_requests_per_minute=0))
    gaps, stop = [], asyncio.Event()

    async def ticker():
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        watcher = asyncio.create_task(ticker())
        reply = await client.post("/v2/chat", json={"message": "hello"})
        stop.set()
        await watcher
    assert reply.status_code == 200 and reply.json()["reply"] == "Hello"
    assert sessions.threads and all(t != MAIN_THREAD for t in sessions.threads)  # the blocking work ran on a worker thread
    assert max(gaps) < 0.15, f"the loop stalled for {max(gaps):.2f}s while the database call blocked"  # three 0.2s calls ran, none on the loop


async def test_concurrent_requests_overlap_instead_of_queueing_behind_a_blocked_loop():
    app = create_app(Services(chat=Chat(), sessions=SlowSessions(), identity=None, kv=SlowKV(), edge_requests_per_minute=0))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        started = time.perf_counter()
        replies = await asyncio.gather(*[client.post("/v2/chat", json={"message": f"hello {i}"}) for i in range(6)])
        elapsed = time.perf_counter() - started
    assert all(r.status_code == 200 for r in replies)
    assert elapsed < 1.5  # six requests, each with two 0.2s blocking calls, run side by side (on the loop they would take 2.4s)


# --- which handlers are plain functions -----------------------------------------------------
def routes_by_name():
    app = create_app(Services(chat=Chat(), sessions=SlowSessions(), identity=None, admin=object(), admin_token="t"))
    return {r.endpoint.__name__: r.endpoint for r in app.routes if hasattr(r, "endpoint")}


def test_handlers_that_touch_the_database_but_never_await_run_on_the_thread_pool():
    endpoints = routes_by_name()
    for name in ("new_session", "session_status", "memory_consent", "memory_list", "memory_forget", "account_export", "account_delete",
                 "account_sessions", "account_revoke", "identity_verify", "admin_overview", "admin_quotes", "admin_merge", "google_status"):
        assert not inspect.iscoroutinefunction(endpoints[name]), f"{name} should be a plain function"


def test_handlers_that_must_stay_async_still_are():
    endpoints = routes_by_name()
    for name in ("chat", "chat_stream", "upload", "voice", "stripe_webhook", "health", "twilio_inbound", "end_session"):
        assert inspect.iscoroutinefunction(endpoints[name]), f"{name} should stay async"


def test_the_converted_handlers_still_answer(monkeypatch):
    class Sessions(SlowSessions):
        def _slow(self):
            pass

        def resume(self, session_id):
            return SimpleNamespace(id="row1", thread_id="t1", verified=False, user_id=None) if session_id == "row1" else None

    client = TestClient(create_app(Services(chat=Chat(), sessions=Sessions(), identity=None, kv=MemoryKV(), edge_requests_per_minute=0)))
    sid = client.post("/v2/session").json()["session_id"]
    assert sid == "row1" and client.get("/v2/session/row1").json() == {"session_id": "row1", "verified": False}
    assert client.get("/v2/session/other").status_code == 404


# --- the pool size --------------------------------------------------------------------------
def test_the_thread_pool_is_sized_from_settings(monkeypatch):
    import anyio.to_thread

    limiter = SimpleNamespace(total_tokens=40)
    monkeypatch.setattr(anyio.to_thread, "current_default_thread_limiter", lambda: limiter)
    with TestClient(create_app(Services(chat=Chat(), sessions=SlowSessions(), identity=None, threadpool_size=96))):
        assert limiter.total_tokens == 96
    limiter.total_tokens = 40
    with TestClient(create_app(Services(chat=Chat(), sessions=SlowSessions(), identity=None, threadpool_size=2))):
        assert limiter.total_tokens == 8  # never smaller than a sensible floor


# --- memory work runs in threads ------------------------------------------------------------
async def test_memory_recall_and_writes_run_off_the_loop():
    seen = {}

    class Store(MemoryStore):
        def recall(self, *a, **kw):
            seen["recall"] = threading.get_ident()
            return []

        def write(self, *a, **kw):
            seen["write"] = threading.get_ident()
            return super().write(*a, **kw)

    class Model:
        async def complete(self, messages, **kw):
            from mpd_assistant.core.llm.client import LLMResult

            return LLMResult('{"memories": [{"kind": "fact", "text": "runs a logistics company", "importance": 0.8, "confidence": 0.9, "slot": null}]}')

    def consent(user_id):
        seen["consent"] = threading.get_ident()
        return True

    wiring = MemoryWiring(Store(), Model(), consent)
    await wiring.before("u1", "Tell me about delivery routes for our fleet")
    await wiring.after("u1", "We run a logistics company with forty trucks across Ontario", allow=True)
    assert set(seen) == {"consent", "recall", "write"} and all(t != MAIN_THREAD for t in seen.values())


# --- bounded calls to Redis and Postgres ----------------------------------------------------
def test_redis_clients_are_built_with_timeouts(monkeypatch):
    import redis

    captured = {}

    class Fake:
        def ping(self):
            return True

    def from_url(url, **kw):
        captured.update(kw)
        return Fake()

    monkeypatch.setattr(redis.Redis, "from_url", from_url)
    app_module._kv("redis://example:6379/0", production=True)
    assert captured == {"socket_timeout": 2.0, "socket_connect_timeout": 2.0, "health_check_interval": 30}


def test_postgres_connections_carry_a_statement_timeout(monkeypatch):
    import psycopg2

    calls = []
    monkeypatch.setattr(psycopg2, "connect", lambda url, **kw: calls.append(kw) or object())
    make_engine("postgresql://u:p@h/d").pool._creator()
    make_engine("postgresql://u:p@h/d", statement_timeout_ms=0).pool._creator()
    make_engine("postgresql://u:p@h/d", statement_timeout_ms=300000).pool._creator()
    assert calls[0] == {"connect_timeout": 5, "options": "-c statement_timeout=15000"}
    assert calls[1]["options"] is None  # 0 turns the limit off
    assert calls[2]["options"] == "-c statement_timeout=300000"
    assert make_engine("postgresql://u:p@h/d").pool.timeout() == 5  # waiting for a free connection gives up after 5 seconds


def test_the_worker_uses_the_longer_statement_timeout():
    source = inspect.getsource(__import__("mpd_assistant.worker.main", fromlist=["build_jobs"]).build_jobs)
    assert "statement_timeout_ms=300000" in source


def test_settings_carry_the_new_limits(monkeypatch):
    for key, value in {"SECRET_KEY": "x" * 16, "DATABASE_URL": "sqlite://", "REDIS_URL": "redis://localhost:1", "DATA_ENCRYPTION_KEY": crypto.generate_key(), "BLIND_INDEX_KEY": crypto.generate_key()}.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert (s.THREADPOOL_SIZE, s.TURN_TIMEOUT_SECONDS, s.TOOL_TIMEOUT_SECONDS, s.LLM_MAX_RETRIES) == (64, 45, 15, 2)
    config.get_settings.cache_clear()


@pytest.mark.parametrize("name", ["new_session", "chat"])
def test_endpoint_names_exist(name):
    assert name in routes_by_name()
