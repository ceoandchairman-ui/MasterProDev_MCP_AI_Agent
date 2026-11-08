"""Orchestration guards: the per-turn deadline, the explicit recursion limit, and what the user sees in each case."""

import asyncio
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from mpd_assistant.core import crypto
from mpd_assistant.graph.service import ChatService
from mpd_assistant.observability.metrics import DEGRADED
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.responses.engine import render


def vault():
    return PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())


def degraded(label):
    return DEGRADED.labels(label)._value.get()


class SlowGraph:
    def __init__(self, seconds):
        self.seconds, self.configs = seconds, []

    async def ainvoke(self, state, config=None):
        self.configs.append(config)
        await asyncio.sleep(self.seconds)
        return {"response": "late", "eval_verdict": "pass", "mode": "reasoned", "intent": "x", "agent": "concierge", "language": "en"}


async def test_a_turn_that_runs_out_of_time_gets_a_retry_message():
    before = degraded("turn_timeout")
    svc = ChatService(SlowGraph(1.0), vault(), turn_timeout=0.05)
    result = await svc.chat("t1", "Tell me about your services", verified=True, user_id="u1")
    assert result.reply == render("temporary_error", "en") and result.eval_reasons == ["turn_timeout"] and not result.escalated
    assert degraded("turn_timeout") == before + 1


async def test_a_fast_turn_is_not_affected_and_the_limits_reach_the_graph():
    graph = SlowGraph(0.0)
    svc = ChatService(graph, vault(), turn_timeout=5.0, recursion_limit=17)
    result = await svc.chat("t2", "Tell me about your services", verified=True, user_id="u1")
    assert result.reply == "late"
    assert graph.configs[0]["recursion_limit"] == 17 and graph.configs[0]["configurable"] == {"thread_id": "t2"}


async def test_no_deadline_means_the_turn_may_take_as_long_as_it_needs():
    svc = ChatService(SlowGraph(0.1), vault(), turn_timeout=None)
    assert (await svc.chat("t3", "Tell me about your services", verified=True, user_id="u1")).reply == "late"


# --- a graph that really loops -------------------------------------------------------------
class Loop(TypedDict):
    n: Annotated[int, lambda a, b: b]


def looping_graph():
    builder = StateGraph(Loop)
    builder.add_node("spin", lambda state: {"n": state.get("n", 0) + 1})
    builder.add_edge(START, "spin")
    builder.add_conditional_edges("spin", lambda state: "spin", {"spin": "spin", END: END})
    return builder.compile()


class Escalations:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def hook(self, state, reason):
        self.calls.append((state, reason))
        if self.fail:
            raise RuntimeError("staff mail down")
        return "REF12345"

    def is_paused(self, session_row):
        return False


async def test_a_runaway_graph_stops_at_the_limit_and_hands_over_to_a_person():
    before = degraded("loop_limit")
    escalations = Escalations()
    svc = ChatService(looping_graph(), vault(), escalations=escalations, recursion_limit=6)
    result = await svc.chat("t4", "Tell me about your services", verified=True, user_id="u1", session_row="row1")
    assert result.escalated and result.reference == "REF12345" and result.eval_reasons == ["loop_limit"]
    assert "REF12345" in result.reply
    state, reason = escalations.calls[0]
    assert reason == "loop_limit" and state["session_row"] == "row1" and state["messages"][0]["role"] == "user"
    assert degraded("loop_limit") == before + 1


async def test_a_failing_escalation_still_ends_with_a_polite_reply():
    svc = ChatService(looping_graph(), vault(), escalations=Escalations(fail=True), recursion_limit=6)
    result = await svc.chat("t5", "Tell me about your services", verified=True, user_id="u1")
    assert not result.escalated and result.reply == render("temporary_error", "en")


async def test_without_an_escalation_service_the_user_still_gets_a_clean_reply():
    svc = ChatService(looping_graph(), vault(), recursion_limit=6)
    result = await svc.chat("t6", "Tell me about your services", verified=True)
    assert result.reply == render("temporary_error", "en") and result.eval_reasons == ["loop_limit"]


def test_the_real_graph_stays_far_below_the_limit():
    """The longest legitimate path: three sub-tasks, each supervisor -> agent -> evaluate -> advance, then persist."""
    from mpd_assistant.routing.decompose import MAX_TASKS

    longest = MAX_TASKS * 4 + 1
    assert longest == 13 and longest < 30  # the configured GRAPH_RECURSION_LIMIT default
