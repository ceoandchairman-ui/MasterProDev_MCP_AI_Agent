"""The tool path: per-service circuit breakers, retries for read-only tools only, a concurrency cap, and daily limits."""

import asyncio
import dataclasses
import json

import httpx
import pytest

from mpd_assistant.agents.comms_scheduling.agent import make_comms
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.resilience import CircuitOpen
from mpd_assistant.integrations.context import reset_token, set_token
from mpd_assistant.observability.metrics import TOOL_CIRCUIT, TOOL_LIMITED, TOOL_RETRIES
from mpd_assistant.responses.engine import render
from mpd_assistant.routing.intents import Agent
from mpd_assistant.tools.executor import ToolContext, ToolExecutor, http_backend
from mpd_assistant.tools.registry import Role, default_registry

REGISTRY = default_registry()
CAL, MAIL = "http://calendar:8001", "http://gmail:8002"
ROUTES = {"get_calendar_events": (CAL, "get_events"), "find_free_slots": (CAL, "find_free_slots"), "send_email": (MAIL, "send_email"), "get_emails": (MAIL, "get_emails")}


def backend(handler, **kw):
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return http_backend(ROUTES, "svc-key", client, REGISTRY, sleep=sleep, **kw), waits


def counter(c, *labels):
    return c.labels(*labels)._value.get()


# --- retries -----------------------------------------------------------------------------
async def test_a_read_only_tool_is_retried_on_a_transient_failure():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"status": "success", "events": []})

    call, waits = backend(handler)
    before = counter(TOOL_RETRIES, "get_calendar_events", "503")
    assert (await call("get_calendar_events", {}))["status"] == "success"
    assert len(calls) == 3 and waits == [0.3, 0.6] and counter(TOOL_RETRIES, "get_calendar_events", "503") == before + 2


async def test_a_write_is_never_repeated():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    call, waits = backend(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await call("send_email", {"to": ["a@example.com"], "subject": "s", "body": "b"})
    assert len(calls) == 1 and waits == []  # one attempt: repeating it could send the mail twice


async def test_client_errors_are_not_retried_and_do_not_count_against_the_service():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401)

    call, waits = backend(handler, breaker_threshold=2)
    for _ in range(4):
        with pytest.raises(httpx.HTTPStatusError):
            await call("get_calendar_events", {})
    assert len(calls) == 4 and waits == []  # four calls reached the server: a 401 never opens the circuit


async def test_network_errors_are_retried_for_reads_then_raised():
    def handler(request):
        raise httpx.ConnectError("refused")

    call, waits = backend(handler, retries=2)
    with pytest.raises(httpx.ConnectError):
        await call("get_emails", {})
    assert len(waits) == 2


# --- circuit breaker ---------------------------------------------------------------------
async def test_a_failing_service_trips_only_its_own_circuit():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(500) if request.url.host == "gmail" else httpx.Response(200, json={"status": "success"})

    call, _ = backend(handler, breaker_threshold=2, breaker_reset=600)
    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            await call("send_email", {"to": ["a@example.com"], "subject": "s", "body": "b"})
    before = counter(TOOL_CIRCUIT, MAIL)
    reached = len(seen)
    with pytest.raises(CircuitOpen):
        await call("get_emails", {})  # a different tool, same dead service
    assert len(seen) == reached and counter(TOOL_CIRCUIT, MAIL) == before + 1  # the request never left
    assert (await call("get_calendar_events", {}))["status"] == "success"  # the calendar service is unaffected


async def test_a_recovered_service_closes_its_circuit():
    state = {"healthy": False}

    def handler(request):
        return httpx.Response(200, json={"status": "success"}) if state["healthy"] else httpx.Response(500)

    call, _ = backend(handler, breaker_threshold=1, breaker_reset=0.0, retries=0)
    with pytest.raises(httpx.HTTPStatusError):
        await call("get_calendar_events", {})
    state["healthy"] = True
    assert (await call("get_calendar_events", {}))["status"] == "success"  # the reset window passed: one probe got through and closed it
    assert (await call("get_calendar_events", {}))["status"] == "success"


# --- plumbing ----------------------------------------------------------------------------
async def test_headers_and_the_users_token_are_sent():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        seen["query"] = dict(request.url.params)
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"status": "success"})

    call, _ = backend(handler)
    marker = set_token("USER-GOOGLE-TOKEN")
    try:
        await call("find_free_slots", {"duration_min": 30})
    finally:
        reset_token(marker)
    assert seen["authorization"] == "Bearer svc-key" and seen["x-google-access-token"] == "USER-GOOGLE-TOKEN"
    assert seen["query"] == {"tool_name": "find_free_slots"} and seen["body"] == {"duration_min": 30}


async def test_unrouted_tools_and_bad_bodies_fail_cleanly():
    call, waits = backend(lambda request: httpx.Response(200, content=b"<html>"))
    with pytest.raises(LookupError):
        await call("memory_search", {})
    with pytest.raises(ValueError):
        await call("get_calendar_events", {})
    assert waits == []


async def test_only_max_concurrency_calls_run_at_once():
    state = {"now": 0, "peak": 0}

    async def handler(request):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        return httpx.Response(200, json={"status": "success"})

    call, _ = backend(handler, max_concurrency=3)
    await asyncio.gather(*[call("get_calendar_events", {}) for _ in range(10)])
    assert state["peak"] == 3


# --- daily limits ------------------------------------------------------------------------
def executor(kv=None, registry=REGISTRY):
    calls = []

    async def fake_backend(tool, args):
        calls.append((tool, args))
        return {"status": "success"}

    return ToolExecutor(registry, fake_backend, kv=kv or MemoryKV()), calls


def send(n):
    return {"to": [f"person{n}@example.com"], "subject": f"Hello {n}", "body": "Thanks"}


def ctx(user="u1", session="s1"):
    return ToolContext(Agent.COMMS_SCHEDULING, Role.VERIFIED, frozenset({"send_email"}), session_id=session, user_id=user)


async def test_a_user_cannot_exceed_a_daily_limit_across_sessions():
    ex, calls = executor()
    limit = REGISTRY.get("send_email").limit_per_day
    assert limit == 20
    for n in range(limit):
        assert (await ex.run("send_email", send(n), ctx(session=f"s{n}"))).status == "ok"  # a new session each time
    before = counter(TOOL_LIMITED, "send_email")
    blocked = await ex.run("send_email", send(99), ctx(session="brand-new-session"))
    assert blocked.status == "denied" and blocked.reason == "daily_limit" and len(calls) == limit
    assert counter(TOOL_LIMITED, "send_email") == before + 1
    assert (await ex.run("send_email", send(1), ctx(user="someone-else"))).status == "ok"  # another person is unaffected


async def test_a_repeated_confirmed_action_does_not_use_up_the_limit():
    ex, calls = executor()
    for _ in range(30):
        assert (await ex.run("send_email", send(1), ctx())).status == "ok"  # the same mail, repeated
    assert len(calls) == 1  # idempotency served the repeats, so they were neither sent nor counted


async def test_reads_have_no_daily_limit():
    ex, calls = executor()
    for _ in range(60):
        assert (await ex.run("get_calendar_events", {}, ToolContext(Agent.COMMS_SCHEDULING, Role.VERIFIED, user_id="u1", session_id="s1"))).status == "ok"
    assert len(calls) == 60


async def test_without_a_store_no_limit_is_applied():
    calls = []

    async def fake_backend(tool, args):
        calls.append(tool)
        return {"status": "success"}

    ex = ToolExecutor(REGISTRY, fake_backend)  # no kv
    for n in range(25):
        await ex.run("send_email", send(n), ctx())
    assert len(calls) == 25


# --- what the user is told ---------------------------------------------------------------
class Planner:
    def __init__(self, plan):
        self.plan = plan

    async def complete(self, messages, **kw):
        return type("R", (), {"text": json.dumps(self.plan), "usage": None})()


async def test_the_comms_agent_explains_a_reached_limit_and_counts_per_user():
    tight = default_registry()
    tight._tools["send_email"] = dataclasses.replace(tight.get("send_email"), limit_per_day=1)
    ex, calls = executor(registry=tight)
    run = make_comms(Planner({}), ex, tight)
    pending = {"tool": "send_email", "args": send(1)}

    def turn(session):
        return {"messages": [{"role": "user", "content": "yes"}], "language": "en", "session_id": session, "user_id": "u1", "pending_action": pending}

    first = await run(turn("s1"))
    assert first["response"].startswith("Done") and len(calls) == 1
    second = await run({**turn("s2"), "pending_action": {"tool": "send_email", "args": send(2)}})  # a different session, same person
    assert second["response"] == render("tool_limit_reached", "en") and len(calls) == 1
    assert render("tool_limit_reached", "fr") != render("tool_limit_reached", "en")
