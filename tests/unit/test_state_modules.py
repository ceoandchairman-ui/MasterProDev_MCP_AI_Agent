import pytest

from mpd_assistant.business.funnel import InvalidTransition, Stage, apply_transition, can_transition
from mpd_assistant.cache.keys import build_key, may_cache, normalize_query
from mpd_assistant.memory.context.assembler import Block, assemble
from mpd_assistant.memory.short_term.window import estimate_tokens, message_tokens, trim_to_budget
from mpd_assistant.routing.intents import Agent, Intent, Mode
from mpd_assistant.sessions.service import (
    ABSOLUTE_TIMEOUT_SECONDS,
    IDLE_TIMEOUT_SECONDS,
    MemorySessionRepository,
    SessionService,
)
from mpd_assistant.tools.registry import Risk, Role, ToolRegistry, ToolSpec, default_registry


# --- window -----------------------------------------------------------------
def test_trim_keeps_recent_and_pinned():
    msgs = [{"role": "system", "content": "rules " * 10, "pinned": True}]
    msgs += [{"role": "user", "content": "x" * 400} for _ in range(10)]
    out = trim_to_budget(msgs, budget_tokens=400)
    assert out[0].get("pinned")
    assert out[-1] is msgs[-1]
    assert len(out) < len(msgs)


def test_trim_never_splits_tool_call_from_result():
    msgs = [
        {"role": "user", "content": "old " * 200},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "result", "tool_call_id": "1"},
        {"role": "user", "content": "latest"},
    ]
    for budget in range(10, 400, 7):
        out = trim_to_budget(msgs, budget)
        roles = [m["role"] for m in out]
        if "tool" in roles:
            assert roles[roles.index("tool") - 1] == "assistant"


def test_trim_truncates_oversized_latest_message():
    out = trim_to_budget([{"role": "user", "content": "y" * 10_000}], 50)
    assert len(out) == 1 and message_tokens(out[0]) <= 60


# --- context assembler --------------------------------------------------------
def test_assembler_caps_memory_share_and_orders_sections():
    sections = {
        "stable_prefix": [Block("SYSTEM")],
        "memories": [Block("m" * 400, score=s) for s in (0.9, 0.5, 0.1)],
        "recent_window": [Block("hello")],
    }
    ctx = assemble(sections, budget_tokens=500)
    memory_tokens = sum(estimate_tokens(b.text) for b in ctx.sections["memories"])
    assert memory_tokens <= 500 * 0.15 + 1
    assert ctx.render().startswith("SYSTEM")


def test_assembler_evicts_in_documented_order_and_keeps_prefix():
    sections = {
        "stable_prefix": [Block("P" * 40)],
        "thread_summary": [Block("S" * 40)],
        "recent_window": [Block("W" * 200), Block("w" * 40)],
        "tool_digests": [Block("T" * 200)],
    }
    ctx = assemble(sections, budget_tokens=60)
    assert ctx.tokens() <= 60
    assert ctx.sections["stable_prefix"]
    assert not ctx.sections["tool_digests"]


def test_assembler_keeps_pinned():
    ctx = assemble({"recent_window": [Block("A" * 400, pinned=True), Block("B" * 400)]}, budget_tokens=110)
    assert [b.text[0] for b in ctx.sections["recent_window"]] == ["A"]


# --- sessions ---------------------------------------------------------------
@pytest.fixture
def clock():
    t = [1000.0]
    return t


def test_session_resume_idle_and_absolute_expiry(clock):
    svc = SessionService(MemorySessionRepository(), clock=lambda: clock[0])
    s = svc.create()
    clock[0] += IDLE_TIMEOUT_SECONDS - 1
    assert svc.resume(s.id)
    clock[0] += IDLE_TIMEOUT_SECONDS + 1
    assert svc.resume(s.id) is None
    s2 = svc.create()
    for _ in range(int(ABSOLUTE_TIMEOUT_SECONDS // (IDLE_TIMEOUT_SECONDS - 1)) + 2):
        clock[0] += IDLE_TIMEOUT_SECONDS - 1
        if svc.resume(s2.id) is None:
            break
    assert svc.resume(s2.id) is None


def test_revocation_sticks_and_revoke_all(clock):
    svc = SessionService(MemorySessionRepository(), clock=lambda: clock[0])
    a, b = svc.create("u1"), svc.create("u1")
    svc.revoke(a.id)
    assert svc.resume(a.id) is None and svc.resume(b.id)
    assert svc.revoke_all_for_user("u1") == 2
    assert svc.resume(b.id) is None


def test_visitor_upgrade_keeps_thread(clock):
    svc = SessionService(MemorySessionRepository(), clock=lambda: clock[0])
    s = svc.create()
    thread = s.thread_id
    up = svc.upgrade_to_verified(s.id, "user-1")
    assert up.verified and up.user_id == "user-1" and up.thread_id == thread


# --- cache ------------------------------------------------------------------
def _key(**kw):
    base = dict(tenant="t", locale="en", mode=Mode.GENERATED, agent="concierge", query="What do you do?", prompt_version="v1", corpus_version="c1")
    base.update(kw)
    return build_key(**base)


def test_cache_key_normalizes_and_versions():
    assert _key(query="what do you do") == _key(query="  What do YOU do?? ")
    assert _key(prompt_version="v2") != _key()
    assert _key(corpus_version="c2") != _key()
    assert _key(user_id="u1") != _key()
    assert normalize_query("A, b!") == "a b"


def test_cache_write_rules():
    ok = dict(intent=Intent.FAQ, query="what do you do", response="We build software.", evaluator_passed=True, used_side_effect_tool=False)
    assert may_cache(**ok)
    assert not may_cache(**{**ok, "evaluator_passed": False})
    assert not may_cache(**{**ok, "used_side_effect_tool": True})
    assert not may_cache(**{**ok, "intent": Intent.BOOK_MEETING})
    assert not may_cache(**{**ok, "response": "Email ann@example.com"})


# --- funnel -----------------------------------------------------------------
def test_funnel_transitions():
    assert can_transition(Stage.NEW, Stage.ENGAGED)
    assert apply_transition(Stage.QUOTED, Stage.WON) is Stage.WON
    with pytest.raises(InvalidTransition):
        apply_transition(Stage.NEW, Stage.WON)
    with pytest.raises(InvalidTransition):
        apply_transition(Stage.WON, Stage.NEW)


# --- tool registry ----------------------------------------------------------
def test_registry_default_deny_and_roles():
    r = default_registry()
    assert r.is_allowed("search_knowledge_base", Role.VISITOR)
    assert not r.is_allowed("send_email", Role.VISITOR)
    assert r.is_allowed("send_email", Role.VERIFIED)
    assert not r.is_allowed("delete_calendar_event", Role.VERIFIED)
    assert r.is_allowed("delete_calendar_event", Role.STAFF)
    assert not r.is_allowed("unknown_tool", Role.STAFF)


def test_registry_enforces_owner_and_rules():
    r = default_registry()
    assert not r.is_allowed("send_email", Role.STAFF, agent=Agent.CONCIERGE)
    assert r.is_allowed("send_email", Role.STAFF, agent=Agent.COMMS_SCHEDULING)
    assert r.get("send_email").needs_confirmation and not r.get("search_knowledge_base").needs_confirmation
    with pytest.raises(ValueError):
        r.register(ToolSpec("send_email", Agent.QUOTE, Risk.WRITE, Role.STAFF))
    with pytest.raises(ValueError):
        ToolRegistry().register(ToolSpec("x", Agent.QUOTE, Risk.WRITE, Role.STAFF, cacheable=True))
