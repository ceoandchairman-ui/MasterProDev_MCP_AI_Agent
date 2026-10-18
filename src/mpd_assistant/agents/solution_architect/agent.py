"""Solution Architect: turns gathered requirements into a schema-validated scope. Code renders the reply."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError

from mpd_assistant.agents.common import parse_json_object
from mpd_assistant.core.llm.client import LLM, LLMError
from mpd_assistant.graph.state import AgentState
from mpd_assistant.responses.engine import render

PROMPT_VERSION = "architect-v1"

SYSTEM = (
    "You are a solution architect. From the project details, output ONLY JSON: "
    '{{"summary": str, "milestones": [{{"name": str, "weeks": int, "deliverables": [str]}}], '
    '"assumptions": [str], "risks": [str]}}. 2 to 6 milestones. Do not include prices or dates. '
    "Reply content in language code '{language}'."
)


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
    return f"{known}\nLatest message: {user}".strip()


def make_solution_architect(llm: LLM, retries: int = 1):
    async def run(state: AgentState) -> Dict[str, Any]:
        language = state.get("language", "en")
        messages = [{"role": "system", "content": SYSTEM.format(language=language)}, {"role": "user", "content": _details(state)}]
        for _ in range(retries + 1):
            try:
                result = await llm.complete(messages, tier="reasoning", max_tokens=900, temperature=0.2)
            except LLMError:
                return {"response": render("temporary_error", language)}
            try:
                scope = Scope.model_validate(parse_json_object(result.text) or {})
            except ValidationError:
                messages.append({"role": "user", "content": "That did not match the required JSON schema. Output only valid JSON."})
                continue
            return {"response": render_scope(scope), "scope": scope.model_dump()}
        return {"response": render("no_answer", language)}

    return run
