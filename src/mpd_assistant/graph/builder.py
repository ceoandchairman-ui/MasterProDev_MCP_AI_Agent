"""LangGraph assembly: supervisor -> (identity gate | template | agent | escalation) -> end.

Agents are injected as async callables so the graph can be tested without an LLM.
"""

import uuid
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

from langgraph.graph import END, START, StateGraph

from mpd_assistant.graph.state import AgentState
from mpd_assistant.responses.engine import TemplateNotFound, render
from mpd_assistant.routing.intents import Agent, Intent, Mode
from mpd_assistant.routing.router import route

Runner = Callable[[AgentState], Awaitable[Dict[str, Any]]]

MAX_STEPS = 6

_TEMPLATE_FOR_INTENT = {Intent.GREETING: "greeting"}


def _last_user_text(state: AgentState) -> str:
    for msg in reversed(state.get("messages", [])):
        if msg.get("role") == "user":
            return str(msg.get("content", ""))
    return ""


async def supervisor(state: AgentState) -> Dict[str, Any]:
    decision = route(_last_user_text(state), verified=state.get("verified", False), language=state.get("language"))
    return {
        "intent": decision.intent.value,
        "agent": decision.agent.value,
        "mode": decision.mode.value,
        "language": decision.language,
        "requires_identity": decision.requires_identity,
        "steps": state.get("steps", 0) + 1,
        "response": None,
    }


def _after_supervisor(state: AgentState) -> str:
    if state.get("steps", 0) > MAX_STEPS:
        return "escalate"
    if state.get("requires_identity"):
        return "identity_gate"
    mode = Mode(state["mode"])
    if mode is Mode.ESCALATE:
        return "escalate"
    if mode is Mode.TEMPLATED and Intent(state["intent"]) in _TEMPLATE_FOR_INTENT:
        return "template"
    return f"agent_{state['agent']}"


async def identity_gate(state: AgentState) -> Dict[str, Any]:
    return {"response": render("identity_required", state.get("language", "en"))}


async def template_node(state: AgentState) -> Dict[str, Any]:
    key = _TEMPLATE_FOR_INTENT[Intent(state["intent"])]
    return {"response": render(key, state.get("language", "en"))}


async def escalation_node(state: AgentState) -> Dict[str, Any]:
    reference = state.get("reference") or uuid.uuid4().hex[:8].upper()
    return {
        "escalated": True,
        "reference": reference,
        "response": render("escalation_notice", state.get("language", "en"), {"reference": reference}),
    }


async def persist(state: AgentState) -> Dict[str, Any]:
    reply = state.get("response") or render("temporary_error", state.get("language", "en"))
    return {"response": reply, "messages": [{"role": "assistant", "content": reply}]}


def _agent_node(runner: Optional[Runner], language_key: str = "no_answer") -> Runner:
    async def node(state: AgentState) -> Dict[str, Any]:
        if runner is None:
            return {"response": render(language_key, state.get("language", "en"))}
        try:
            return await runner(state)
        except TemplateNotFound:
            raise
        except Exception:
            return {"response": render("temporary_error", state.get("language", "en"))}

    return node


def build_graph(runners: Optional[Mapping[Agent, Runner]] = None, checkpointer: Any = None):
    runners = runners or {}
    graph = StateGraph(AgentState)

    graph.add_node("supervisor", supervisor)
    graph.add_node("identity_gate", identity_gate)
    graph.add_node("template", template_node)
    graph.add_node("escalate", escalation_node)
    graph.add_node("persist", persist)

    agent_targets = {}
    for agent in Agent:
        if agent is Agent.ESCALATION:
            continue
        name = f"agent_{agent.value}"
        graph.add_node(name, _agent_node(runners.get(agent)))
        agent_targets[name] = name
    # The escalation agent is the escalation node.
    agent_targets["agent_escalation"] = "escalate"

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _after_supervisor,
        {"identity_gate": "identity_gate", "template": "template", "escalate": "escalate", **agent_targets},
    )
    for name in ("identity_gate", "template", "escalate", *[n for n in agent_targets if n != "agent_escalation"]):
        graph.add_edge(name, "persist")
    graph.add_edge("persist", END)

    return graph.compile(checkpointer=checkpointer)
