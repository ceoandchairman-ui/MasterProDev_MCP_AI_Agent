"""Payment step: deterministic code, no model. Confirms the stored quote, requires recent step-up verification, then
hands out a Stripe-hosted checkout link. The quote is only ever marked paid by the signed webhook."""

import re
from collections.abc import Awaitable, Callable
from typing import Any, Dict

from mpd_assistant.agents.common import is_affirmative, is_negative
from mpd_assistant.agents.quote.agent import money
from mpd_assistant.business.payments import PaymentService
from mpd_assistant.graph.state import AgentState
from mpd_assistant.responses.engine import render

_REF = re.compile(r"\b([0-9a-fA-F]{8})\b")

REFUSAL_TEMPLATE = {
    "no_quote": "payment_no_quote",
    "needs_approval": "quote_needs_review",
    "expired": "payment_expired",
    "already_paid": "payment_already_paid",
}


def _last_user(state: AgentState) -> str:
    return next((m["content"] for m in reversed(state.get("messages", [])) if m.get("role") == "user"), "")


def make_payment_node(
    payments: PaymentService,
    has_step_up: Callable[[str], bool] | None = None,
    start_step_up: Callable[[str], Awaitable[bool]] | None = None,
):
    async def run(state: AgentState) -> Dict[str, Any]:
        language = state.get("language", "en")
        user_id = state.get("user_id")
        if not user_id or not state.get("verified"):
            return {"response": render("identity_required", language), "pending_action": None}
        if not payments.configured:
            return {"response": render("payment_refused", language), "pending_action": None}

        text = _last_user(state)
        pending = state.get("pending_action") or {}
        if pending.get("type") == "payment":
            if is_negative(text):
                return {"response": render("payment_cancelled", language), "pending_action": None}
            if is_affirmative(text):
                if has_step_up and not has_step_up(state.get("session_row") or ""):
                    if start_step_up:
                        await start_step_up(user_id)
                    return {"response": render("step_up_required", language), "pending_action": pending}
                result = await payments.start_checkout(user_id, pending.get("ref"))
                if result.ok and result.quote and result.url:
                    return {"response": render("payment_link", language, {"quote": result.quote.ref, "link": result.url}), "pending_action": None}
                return {"response": render(REFUSAL_TEMPLATE.get(result.reason, "payment_refused"), language), "pending_action": None}

        match = _REF.search(text)
        quote, reason = payments.check(user_id, match.group(1) if match else None)
        if reason or quote is None:
            return {"response": render(REFUSAL_TEMPLATE.get(reason, "payment_refused"), language), "pending_action": None}
        return {
            "response": render("payment_confirm", language, {"quote": quote.ref, "total": money(quote.total_cents, quote.currency)}),
            "pending_action": {"type": "payment", "ref": quote.ref},
        }

    return run


__all__ = ["make_payment_node"]
