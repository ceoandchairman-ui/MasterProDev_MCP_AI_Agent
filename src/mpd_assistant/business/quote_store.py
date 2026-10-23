"""Stored quotes. Payment reads the amount from here by id, never from conversation state or model output.

Statuses: draft -> accepted -> paid, or needs_approval -> approved -> accepted -> paid, or needs_approval -> rejected, or expired.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Dict, List, Protocol

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.business.quoting import Quote as BuiltQuote
from mpd_assistant.core.models import Lead
from mpd_assistant.core.models import Quote as QuoteRow

PAYABLE = frozenset({"draft", "approved", "accepted"})


@dataclass
class StoredQuote:
    id: str
    user_id: str
    total_cents: int
    currency: str
    content_hash: str
    status: str
    expires_at: datetime | None
    lines: List[dict] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return self.id[:8].upper()

    def hash_inputs(self) -> List[List[object]]:
        return [[x["sku"], x["quantity"], x["unit_price_cents"], x["total_cents"]] for x in self.lines]


class QuoteRepository(Protocol):
    def save(self, user_id: str, quote: BuiltQuote) -> StoredQuote: ...
    def get(self, quote_id: str) -> StoredQuote | None: ...
    def find_for_user(self, user_id: str, ref: str | None = None) -> StoredQuote | None: ...
    def set_status(self, quote_id: str, status: str) -> None: ...
    def find_by_ref(self, ref: str) -> StoredQuote | None: ...
    def list_by_status(self, status: str, limit: int = 50) -> List[StoredQuote]: ...


def _line_rows(quote: BuiltQuote) -> List[dict]:
    return [
        {"sku": x.sku, "name": x.name, "quantity": str(x.quantity), "unit_price_cents": x.unit_price_cents, "total_cents": x.total_cents}
        for x in quote.lines
    ]


def _initial_status(quote: BuiltQuote) -> str:
    return "needs_approval" if quote.needs_approval else "draft"


class MemoryQuoteRepository:
    def __init__(self):
        self._items: Dict[str, StoredQuote] = {}

    def save(self, user_id: str, quote: BuiltQuote) -> StoredQuote:
        stored = StoredQuote(uuid.uuid4().hex, user_id, quote.total_cents, quote.currency, quote.content_hash, _initial_status(quote), quote.expires_at, _line_rows(quote))
        self._items[stored.id] = stored
        return stored

    def get(self, quote_id: str) -> StoredQuote | None:
        return self._items.get(quote_id)

    def find_for_user(self, user_id: str, ref: str | None = None) -> StoredQuote | None:
        mine = [q for q in self._items.values() if q.user_id == user_id]
        if ref:
            mine = [q for q in mine if q.id.upper().startswith(ref.upper())]
        return mine[-1] if mine else None

    def set_status(self, quote_id: str, status: str) -> None:
        if quote_id in self._items:
            self._items[quote_id].status = status

    def find_by_ref(self, ref: str) -> StoredQuote | None:
        matches = [q for q in self._items.values() if q.id.upper().startswith(ref.upper())] if len(ref) >= 8 else []
        return matches[0] if len(matches) == 1 else None

    def list_by_status(self, status: str, limit: int = 50) -> List[StoredQuote]:
        return [q for q in self._items.values() if q.status == status][:limit]


class SqlQuoteRepository:
    def __init__(self, engine: Engine, tenant_id: str):
        self._engine, self._tenant = engine, tenant_id

    @staticmethod
    def _domain(row: QuoteRow, user_id: str) -> StoredQuote:
        expires = row.expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return StoredQuote(row.id, user_id, row.total_cents, row.currency, row.content_hash, row.status, expires, list(row.line_items or []))

    def save(self, user_id: str, quote: BuiltQuote) -> StoredQuote:
        with DbSession(self._engine) as db:
            lead = db.scalar(select(Lead).where(Lead.tenant_id == self._tenant, Lead.user_id == user_id))
            if lead is None:
                lead = Lead(tenant_id=self._tenant, user_id=user_id, stage="new")
                db.add(lead)
                db.flush()
            version = len(list(db.scalars(select(QuoteRow.id).where(QuoteRow.lead_id == lead.id)))) + 1
            row = QuoteRow(
                lead_id=lead.id,
                version=version,
                line_items=_line_rows(quote),
                total_cents=quote.total_cents,
                currency=quote.currency,
                content_hash=quote.content_hash,
                status=_initial_status(quote),
                expires_at=quote.expires_at,
            )
            db.add(row)
            db.commit()
            return self._domain(row, user_id)

    def get(self, quote_id: str) -> StoredQuote | None:
        with DbSession(self._engine) as db:
            row = db.get(QuoteRow, quote_id)
            if row is None:
                return None
            lead = db.get(Lead, row.lead_id)
            return self._domain(row, lead.user_id if lead else "")

    def find_for_user(self, user_id: str, ref: str | None = None) -> StoredQuote | None:
        with DbSession(self._engine) as db:
            query = (
                select(QuoteRow)
                .join(Lead, Lead.id == QuoteRow.lead_id)
                .where(Lead.tenant_id == self._tenant, Lead.user_id == user_id)
                .order_by(QuoteRow.created_at.desc())
            )
            for row in db.scalars(query):
                if not ref or row.id.upper().startswith(ref.upper()):
                    return self._domain(row, user_id)
            return None

    def set_status(self, quote_id: str, status: str) -> None:
        with DbSession(self._engine) as db:
            row = db.get(QuoteRow, quote_id)
            if row is not None:
                row.status = status
                db.commit()

    def find_by_ref(self, ref: str) -> StoredQuote | None:
        if len(ref) < 8:
            return None
        with DbSession(self._engine) as db:
            rows = db.execute(
                select(QuoteRow, Lead.user_id).join(Lead, Lead.id == QuoteRow.lead_id).where(Lead.tenant_id == self._tenant, QuoteRow.id.like(ref.lower() + "%"))
            ).all()
            return self._domain(rows[0][0], rows[0][1]) if len(rows) == 1 else None

    def list_by_status(self, status: str, limit: int = 50) -> List[StoredQuote]:
        with DbSession(self._engine) as db:
            rows = db.execute(
                select(QuoteRow, Lead.user_id)
                .join(Lead, Lead.id == QuoteRow.lead_id)
                .where(Lead.tenant_id == self._tenant, QuoteRow.status == status)
                .order_by(QuoteRow.created_at)
                .limit(limit)
            ).all()
            return [self._domain(row, user_id) for row, user_id in rows]


__all__ = ["MemoryQuoteRepository", "PAYABLE", "QuoteRepository", "SqlQuoteRepository", "StoredQuote"]
