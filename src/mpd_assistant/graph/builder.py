"""LangGraph assembly: supervisor -> (identity gate | template | agent | escalation) -> end.

Agents are injected as async callables so the graph can be tested without an LLM.
"""

import uuid
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

from langgraph.graph import END, START, StateGraph

from mpd_assistant.agents.common import is_affirmative, is_negative
from mpd_assistant.evaluation.online.rules import Verdict, evaluate_response
from mpd_assistant.graph.state import AgentState
from mpd_assistant.responses.engine import TemplateNotFound, render
from mpd_assistant.routing.intents import Agent, Intent, Mode
from mpd_assistant.routing.decompose import split_tasks
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
    text = state.get("current_task") or _last_user_text(state)
    pending = state.get("pending_action")
    if not state.get("current_task") and pending and state.get("verified") and (is_affirmative(text) or is_negative(text)):
        # A bare yes/no answers the agent that asked, not a fresh intent.
        return {"evidence": None, "mode": Mode.REASONED.value, "requires_identity": False, "steps": state.get("steps", 0) + 1, "response": None}

    split: Dict[str, Any] = {}
    if not state.get("current_task"):
        parts = split_tasks(text, verified=state.get("verified", False), language=state.get("language"))
        if len(parts) > 1:
            # Each part is handled in turn by the agent that owns it; the replies are joined in persist.
            text = parts[0]
            split = {"current_task": parts[0], "task_queue": parts[1:], "partials": [], "messages": [{"role": "user", "content": parts[0], "synthetic": True}]}

    decision = route(text, verified=state.get("verified", False), language=state.get("language"))
    return {
        **split,
        "intent": decision.intent.value,
        "agent": decision.agent.value,
        "mode": decision.mode.value,
        "language": decision.language,
        "requires_identity": decision.requires_identity,
        "steps": state.get("steps", 0) + 1,
        "response": None,
        "pending_action": None,
        "evidence": None,
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


EscalationHook = Callable[[AgentState, str], Awaitable[Optional[str]]]


def make_escalation_node(hook: Optional[EscalationHook] = None):
    """The hook saves the escalation and alerts staff; it returns the reference to show the user."""

    async def node(state: AgentState) -> Dict[str, Any]:
        reason = state.get("intent") or "evaluator"
        reference = None
        if hook is not None:
            try:
                reference = await hook(state, reason)
            except Exception:
                reference = None  # the user still gets a handover message; staff alerting failures are logged by the hook
        reference = reference or state.get("reference") or uuid.uuid4().hex[:8].upper()
        return {
            "escalated": True,
            "reference": reference,
            "response": render("escalation_notice", state.get("language", "en"), {"reference": reference}),
        }

    return node


escalation_node = make_escalation_node(None)


def make_evaluate(escalate, judge=None):
    async def evaluate(state: AgentState) -> Dict[str, Any]:
        result = evaluate_response(state.get("response"), language=state.get("language", "en"), allow_tokens=True)
        update: Dict[str, Any] = {"eval_verdict": result.verdict.value, "eval_reasons": result.reasons}
        if result.verdict is Verdict.PASS and judge is not None and state.get("evidence") and judge.should_judge():
            review = await judge.review(state.get("response") or "", state["evidence"])
            if review.judged and review.supported < judge.threshold:
                update["eval_verdict"] = Verdict.REVISE.value
                update["eval_reasons"] = ["unsupported_claim"]
                update["response"] = render("no_answer", state.get("language", "en"))
            return update
        if result.verdict is Verdict.REVISE:
            update["response"] = render("temporary_error", state.get("language", "en"))
        elif result.verdict is Verdict.ESCALATE:
            update.update(await escalate({**state, "intent": "pii_leak"}))
        return update

    return evaluate


evaluate = make_evaluate(escalation_node)


async def advance(state: AgentState) -> Dict[str, Any]:
    """Finish one sub-task and start the next one through the supervisor."""
    queue = list(state.get("task_queue") or [])
    partials = list(state.get("partials") or [])
    response = state.get("response")
    if response and response not in partials:
        partials.append(response)
    following = queue.pop(0)
    return {
        "partials": partials,
        "task_queue": queue,
        "current_task": following,
        "response": None,
        "evidence": None,
        "messages": [{"role": "user", "content": following, "synthetic": True}],
    }


def _after_evaluate(state: AgentState) -> str:
    """Carry on with queued sub-tasks unless a person was asked for or the agent is waiting on the user's answer."""
    if state.get("task_queue") and not state.get("escalated") and not state.get("pending_action"):
        return "advance"
    return "persist"


async def persist(state: AgentState) -> Dict[str, Any]:
    language = state.get("language", "en")
    reply = state.get("response") or render("temporary_error", language)
    parts = list(state.get("partials") or [])
    if reply not in parts:
        parts.append(reply)
    remaining = state.get("task_queue") or []
    if remaining:
        parts.append(render("tasks_remaining", language, {"tasks": "; ".join(remaining)}))
    reply = "\n\n".join(parts)
    return {
        "response": reply,
        "messages": [{"role": "assistant", "content": reply}],
        "task_queue": [],
        "partials": [],
        "current_task": None,
    }


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


def build_graph(
    runners: Optional[Mapping[Agent, Runner]] = None,
    checkpointer: Any = None,
    escalation_hook: Optional[EscalationHook] = None,
    judge: Any = None,
):
    runners = runners or {}
    graph = StateGraph(AgentState)
    escalate_node = make_escalation_node(escalation_hook)

    graph.add_node("supervisor", supervisor)
    graph.add_node("identity_gate", identity_gate)
    graph.add_node("template", template_node)
    graph.add_node("escalate", escalate_node)
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
    graph.add_node("evaluate", make_evaluate(escalate_node, judge))
    for name in ("identity_gate", "template", "escalate", *[n for n in agent_targets if n != "agent_escalation"]):
        graph.add_edge(name, "evaluate")
    graph.add_node("advance", advance)
    graph.add_conditional_edges("evaluate", _after_evaluate, {"advance": "advance", "persist": "persist"})
    graph.add_edge("advance", "supervisor")
    graph.add_edge("persist", END)

    return graph.compile(checkpointer=checkpointer)
