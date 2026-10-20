"""Comms & Scheduling: plans calendar/email actions, executes through the guarded tool executor.

Side effects always wait for an explicit user confirmation on the next turn.
"""

from typing import Any, Dict

from mpd_assistant.agents.common import PlanStep, is_affirmative, is_negative, parse_plan
from mpd_assistant.agents.context import HISTORY_BUDGET, recent_turns
from mpd_assistant.agents.prompts import load_prompt
from mpd_assistant.core.llm.client import LLM, LLMError
from mpd_assistant.graph.state import AgentState
from mpd_assistant.responses.engine import render
from mpd_assistant.routing.intents import Agent
from mpd_assistant.tools.executor import ToolContext, ToolExecutor
from mpd_assistant.tools.registry import Role

PLANNER = load_prompt("comms_scheduling", "planner")
PROMPT_VERSION = PLANNER.version


def _last_user(state: AgentState) -> str:
    return next((m["content"] for m in reversed(state.get("messages", [])) if m.get("role") == "user"), "")


def make_comms(llm: LLM, executor: ToolExecutor, registry, on_booked=None, token_provider=None):
    allowed = [s.name for s in registry.for_agent(Agent.COMMS_SCHEDULING, Role.VERIFIED)]
    catalog = registry.describe(Agent.COMMS_SCHEDULING, Role.VERIFIED)

    async def execute(steps, language: str, confirmed: frozenset, session_id: str, state: AgentState) -> Dict[str, Any]:
        done = []
        tainted = False
        google_token = await token_provider(state.get("user_id")) if token_provider else None
        if token_provider and not google_token:
            return {"response": render("google_connect_needed", language), "pending_action": None}
        for step in steps:
            problems = registry.validate_args(step.tool, step.args)
            if problems:
                return {"response": "I can't do that yet: " + "; ".join(problems[:3]) + ". Could you give me those details?", "pending_action": None}
            step = PlanStep(step.tool, registry.clean_args(step.tool, step.args))
            outcome = await executor.run(
                step.tool,
                step.args,
                ToolContext(Agent.COMMS_SCHEDULING, Role.VERIFIED, confirmed, untrusted_content_in_context=tainted, session_id=session_id, google_access_token=google_token, session_row=state.get("session_row") or "", user_id=state.get("user_id")),
            )
            tainted = tainted or outcome.untrusted
            if outcome.status == "needs_confirmation":
                pending = {"tool": step.tool, "args": step.args}
                question = f"I'm ready to run {step.tool} with {step.args}. Shall I go ahead? (yes/no)"
                return {"response": question, "pending_action": pending}
            if outcome.reason == "daily_limit":
                return {"response": render("tool_limit_reached", language), "pending_action": None}
            if outcome.status != "ok":
                return {"response": render("temporary_error", language), "pending_action": None}
            done.append(f"{step.tool}: {outcome.output}")
            if on_booked and step.tool == "create_calendar_event":
                try:
                    await on_booked(state, step.args)
                except Exception:
                    pass  # a failed confirmation message must never undo or hide the booking
        return {"response": "Done. " + " ".join(done)[:600], "pending_action": None}

    async def run(state: AgentState) -> Dict[str, Any]:
        language = state.get("language", "en")
        text = _last_user(state)
        pending = state.get("pending_action")

        if pending:
            if is_affirmative(text):
                step = PlanStep(pending["tool"], pending["args"])
                return await execute([step], language, frozenset({step.tool}), state.get("session_id", ""), state)
            if is_negative(text):
                return {"response": "Okay, I won't do that.", "pending_action": None}

        try:
            planned = await llm.complete(
                [{"role": "system", "content": PLANNER.render(tools=catalog)}, *recent_turns(state, HISTORY_BUDGET["comms"]), {"role": "user", "content": text}],
                tier="mid",
                max_tokens=300,
                temperature=0.0,
            )
        except LLMError:
            return {"response": render("temporary_error", language)}

        steps = parse_plan(planned.text, allowed, max_steps=3)
        if not steps:
            return {"response": "Could you share a few more details so I can do that?", "pending_action": None}
        return await execute(steps, language, frozenset(), state.get("session_id", ""), state)

    return run
