"""Solution Architect: turns gathered requirements into a schema-validated scope. Code renders the reply."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError

from mpd_assistant.agents.common import memory_note, parse_json_object
from mpd_assistant.agents.prompts import load_prompt
from mpd_assistant.core.llm.client import LLM, LLMError
from mpd_assistant.graph.prar import PrarState, build_prar
from mpd_assistant.graph.state import AgentState
from mpd_assistant.observability.metrics import PRAR_PHASE
from mpd_assistant.responses.engine import render

SYSTEM = load_prompt("solution_architect", "system")
PROMPT_VERSION = SYSTEM.version


class Milestone(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    weeks: int = Field(ge=1, le=52)
    deliverables: List[str] = Field(min_length=1, max_length=8)


class Scope(BaseModel):
    summary: str = Field(min_length=1, max_length=600)
    milestones: List[Milestone] = Field(min_length=1, max_length=8)
    assumptions: List[str] = Field(default_factory=list, max_length=8)
    risks: List[str] = Field(default_factory=list, max_length=8)


def render_scope(scope: Scope) -> str:
    lines = [scope.summary, ""]
    for i, m in enumerate(scope.milestones, 1):
        lines.append(f"{i}. {m.name} (~{m.weeks} wk): " + "; ".join(m.deliverables))
    if scope.assumptions:
        lines += ["", "Assumptions: " + "; ".join(scope.assumptions)]
    if scope.risks:
        lines += ["Risks: " + "; ".join(scope.risks)]
    return "\n".join(lines)


def _details(state: AgentState) -> str:
    slots = state.get("lead_slots") or {}
    user = next((m["content"] for m in reversed(state.get("messages", [])) if m.get("role") == "user"), "")
    known = "\n".join(f"{k}: {v}" for k, v in slots.items())
    return f"{memory_note(state)}{known}\nLatest message: {user}".strip()


RETRY_NOTE = "That did not match the required JSON schema. Output only valid JSON."


def make_solution_architect(llm: LLM, retries: int = 1):
    """Plan (draft the scope), act (validate it against the schema), reflect (re-plan with the error if it failed).
    The loop is bounded by `retries`, and each phase's time is recorded."""

    async def run(state: AgentState) -> Dict[str, Any]:
        language = state.get("language", "en")
        base = [{"role": "system", "content": SYSTEM.render(language=language)}, {"role": "user", "content": _details(state)}]

        async def planner(s: PrarState):
            messages = base + ([{"role": "user", "content": s["reflection"]}] if s.get("reflection") else [])
            result = await llm.complete(messages, tier="reasoning", max_tokens=900, temperature=0.2)
            return [{"draft": result.text}]

        async def actor(step, s: PrarState):
            try:
                scope = Scope.model_validate(parse_json_object(step["draft"]) or {})
            except ValidationError:
                return {"ok": False}
            return {"ok": True, "scope": scope}

        async def reflector(s: PrarState):
            last = s["observations"][-1]
            if last["ok"]:
                return {"done": True, "answer": None, "note": ""}
            return {"done": False, "note": RETRY_NOTE}

        try:
            out = await build_prar(planner, actor, reflector, max_loops=retries + 1).ainvoke({"goal": "scope", "context": {}})
        except LLMError:
            return {"response": render("temporary_error", language)}
        for phase, seconds in out.get("timings", {}).items():
            PRAR_PHASE.labels("solution_architect", phase).observe(seconds)
        last = (out.get("observations") or [{"ok": False}])[-1]
        if not last["ok"]:
            return {"response": render("no_answer", language)}
        scope = last["scope"]
        return {"response": render_scope(scope), "scope": scope.model_dump()}

    return run
