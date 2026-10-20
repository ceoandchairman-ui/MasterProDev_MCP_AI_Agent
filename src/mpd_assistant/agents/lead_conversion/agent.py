"""Lead Conversion: collects need, timeline and budget; code decides the funnel stage."""

from typing import Any, Dict, Protocol

from mpd_assistant.agents.common import parse_json_object
from mpd_assistant.agents.prompts import load_prompt
from mpd_assistant.business.funnel import InvalidTransition, Stage, apply_transition
from mpd_assistant.core.llm.client import LLM, LLMError
from mpd_assistant.graph.state import AgentState
from mpd_assistant.responses.engine import render

EXTRACT = load_prompt("lead_conversion", "extract")
PROMPT_VERSION = EXTRACT.version
SLOTS = ("need", "timeline", "budget")  # all required before a lead counts as qualified
OPTIONAL_SLOTS = ("company",)  # recorded when the user volunteers it; never asked for or required
MAX_SLOT_CHARS = 200


class LeadRepository(Protocol):
    def upsert(self, user_id: str | None, stage: str, slots: Dict[str, str]) -> None: ...


class MemoryLeadRepository:
    def __init__(self):
        self.rows: Dict[str, Dict[str, Any]] = {}

    def upsert(self, user_id: str | None, stage: str, slots: Dict[str, str]) -> None:
        self.rows[user_id or "anonymous"] = {"stage": stage, "slots": dict(slots)}


def _last_user(state: AgentState) -> str:
    return next((m["content"] for m in reversed(state.get("messages", [])) if m.get("role") == "user"), "")


def _merge_slots(existing: Dict[str, str], raw: str) -> Dict[str, str]:
    obj = parse_json_object(raw) or {}
    merged = dict(existing)
    for slot in SLOTS + OPTIONAL_SLOTS:
        value = obj.get(slot)
        if isinstance(value, str) and value.strip() and value.strip().lower() != "null":
            merged[slot] = value.strip()[:MAX_SLOT_CHARS]
    return merged


def _advance(current: Stage, target: Stage) -> Stage:
    """Walk the allowed path toward target one step at a time; stop where the state machine stops."""
    order = [Stage.NEW, Stage.ENGAGED, Stage.QUALIFIED]
    stage = current
    for nxt in order[order.index(current) + 1 : order.index(target) + 1] if current in order else []:
        try:
            stage = apply_transition(stage, nxt)
        except InvalidTransition:
            break
    return stage


def make_lead_conversion(llm: LLM, leads: LeadRepository, companies=None):
    async def run(state: AgentState) -> Dict[str, Any]:
        language = state.get("language", "en")
        slots = dict(state.get("lead_slots") or {})
        stage = Stage(state.get("lead_stage") or Stage.NEW.value)

        try:
            result = await llm.complete(
                [{"role": "system", "content": EXTRACT.render()}, {"role": "user", "content": _last_user(state)}],
                tier="cheap",
                max_tokens=200,
                temperature=0.0,
            )
            slots = _merge_slots(slots, result.text)
        except LLMError:
            pass  # keep what we know; still ask the next question

        if companies is not None and slots.get("company") and state.get("user_id"):
            try:
                companies.link_user(state["user_id"], slots["company"])
            except Exception:
                pass  # a failed customer-record write must never block the conversation

        missing = [s for s in SLOTS if s not in slots]
        stage = _advance(stage, Stage.ENGAGED)
        if not missing:
            stage = _advance(stage, Stage.QUALIFIED)
        leads.upsert(state.get("user_id"), stage.value, slots)

        reply = render(f"ask_{missing[0]}", language) if missing else render("offer_call", language)
        return {"response": reply, "lead_slots": slots, "lead_stage": stage.value}

    return run
