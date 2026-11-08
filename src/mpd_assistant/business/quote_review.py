"""Staff review of quotes the pricing rules held back (needs_approval). Nothing else can make such a quote payable."""

import logging
from collections.abc import Awaitable, Callable
from typing import List

from mpd_assistant.business.quote_store import QuoteRepository, StoredQuote

logger = logging.getLogger(__name__)

AuditSink = Callable[[str, str, str | None, dict], None]
DecisionCallback = Callable[[StoredQuote, bool], Awaitable[None]]


class QuoteReview:
    def __init__(self, quotes: QuoteRepository, audit: AuditSink | None = None, on_decision: DecisionCallback | None = None):
        self._quotes, self._audit, self._on_decision = quotes, audit, on_decision

    def pending(self, limit: int = 50) -> List[StoredQuote]:
        return self._quotes.list_by_status("needs_approval", limit)

    async def decide(self, ref: str, approve: bool, actor: str = "staff") -> str:
        """approved | rejected | not_found | not_pending. Only a quote waiting for review can be decided, and only once."""
        quote = self._quotes.find_by_ref(ref.strip())
        if quote is None:
            return "not_found"
        if quote.status != "needs_approval":
            return "not_pending"
        status = "approved" if approve else "rejected"
        self._quotes.set_status(quote.id, status)
        if self._audit is not None:
            self._audit(actor, f"quote_{status}", quote.ref, {"total_cents": quote.total_cents, "currency": quote.currency})
        if self._on_decision is not None:
            try:
                await self._on_decision(quote, approve)
            except Exception:
                logger.exception("quote decision notice failed for %s", quote.ref)  # the decision stands even if the email fails
        return status
