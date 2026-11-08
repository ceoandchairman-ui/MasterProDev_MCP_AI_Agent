"""Quote: the model picks catalog items and quantities; code prices them and writes the amounts."""

from typing import Any, Dict

from mpd_assistant.agents.common import parse_json_object
from mpd_assistant.agents.prompts import load_prompt
from mpd_assistant.business.quoting import CatalogItem, Quote, QuoteError, build_quote
from mpd_assistant.core.llm.client import LLM, LLMError
from mpd_assistant.graph.state import AgentState
from mpd_assistant.responses.engine import render

SYSTEM = load_prompt("quote", "system")
PROMPT_VERSION = SYSTEM.version


def money(cents: int, currency: str) -> str:
    return f"${cents / 100:,.2f} {currency}"


def render_quote(quote: Quote) -> str:
    lines = [f"- {x.name} x {x.quantity}: {money(x.total_cents, quote.currency)}" for x in quote.lines]
    lines.append(f"Subtotal: {money(quote.subtotal_cents, quote.currency)}")
    lines.append(f"Tax: {money(quote.tax_cents, quote.currency)}")
    lines.append(f"Total: {money(quote.total_cents, quote.currency)} (valid until {quote.expires_at:%Y-%m-%d})")
    return "\n".join(lines)


def make_quote_agent(llm: LLM, catalog: Dict[str, CatalogItem], on_quote=None, on_review=None):
    skus = ", ".join(sorted(catalog))

    async def run(state: AgentState) -> Dict[str, Any]:
        language = state.get("language", "en")
        scope = state.get("scope")
        if not scope:
            return {"response": "I need a project scope before I can prepare a quote. Shall I draft one from what you've told me?"}
        try:
            result = await llm.complete(
                [{"role": "system", "content": SYSTEM.render(skus=skus)}, {"role": "user", "content": str(scope)}],
                tier="mid",
                max_tokens=300,
                temperature=0.0,
            )
        except LLMError:
            return {"response": render("temporary_error", language)}

        selections = (parse_json_object(result.text) or {}).get("selections") or []
        try:
            quote = build_quote(catalog, selections)
        except QuoteError:
            return {"response": "I couldn't build a reliable quote from that scope. Could you tell me more about what you need?"}

        stored = on_quote(state, quote) if on_quote else None
        ids = {"quote_id": stored.id} if stored else {}
        if quote.needs_approval:
            reference = await on_review(state, "quote_review") if on_review else None
            note = render("quote_needs_review", language)
            return {
                "response": f"{note} ({reference})" if reference else note,
                "quote_hash": quote.content_hash,
                "escalated": bool(reference),
                "reference": reference,
                **ids,
            }
        footer = f"\nQuote reference: {stored.ref}" if stored else ""
        return {"response": render_quote(quote) + footer, "quote_hash": quote.content_hash, **ids}

    return run
