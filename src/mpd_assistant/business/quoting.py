"""Deterministic quote engine. The model never produces prices: it selects catalog items, code prices them."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List

APPROVAL_THRESHOLD_CENTS = 2_500_000  # quotes at or above this need a human (placeholder until the business sets it)
QUOTE_VALIDITY_DAYS = 30


class QuoteError(ValueError):
    pass


@dataclass(frozen=True)
class CatalogItem:
    sku: str
    name: str
    unit: str  # hour | fixed | month
    unit_price_cents: int


@dataclass(frozen=True)
class LineItem:
    sku: str
    name: str
    quantity: Decimal
    unit_price_cents: int
    total_cents: int


@dataclass(frozen=True)
class Quote:
    lines: List[LineItem]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    currency: str
    needs_approval: bool
    expires_at: datetime
    content_hash: str


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def build_quote(
    catalog: Dict[str, CatalogItem],
    selections: List[Dict[str, object]],
    *,
    tax_rate: Decimal = Decimal("0.13"),
    currency: str = "CAD",
    now: datetime | None = None,
) -> Quote:
    """selections: [{"sku": "...", "quantity": 12}]. Unknown SKUs and non-positive quantities are rejected."""
    if not selections:
        raise QuoteError("A quote needs at least one line item")
    lines: List[LineItem] = []
    for sel in selections:
        sku = str(sel.get("sku", ""))
        item = catalog.get(sku)
        if item is None:
            raise QuoteError(f"Unknown catalog item: {sku}")
        try:
            quantity = Decimal(str(sel.get("quantity", 0)))
        except Exception as exc:
            raise QuoteError("Invalid quantity") from exc
        if quantity <= 0 or quantity > 100_000:
            raise QuoteError("Quantity out of range")
        lines.append(LineItem(item.sku, item.name, quantity, item.unit_price_cents, _cents(quantity * item.unit_price_cents)))

    subtotal = sum(line.total_cents for line in lines)
    tax = _cents(Decimal(subtotal) * tax_rate)
    total = subtotal + tax
    expires = (now or datetime.now(UTC)) + timedelta(days=QUOTE_VALIDITY_DAYS)
    payload = json.dumps(
        {"lines": [[x.sku, str(x.quantity), x.unit_price_cents, x.total_cents] for x in lines], "total": total, "currency": currency},
        sort_keys=True,
    )
    return Quote(lines, subtotal, tax, total, currency, total >= APPROVAL_THRESHOLD_CENTS, expires, hashlib.sha256(payload.encode()).hexdigest())


def verify_quote_for_payment(quote: Quote, presented_hash: str, now: datetime | None = None) -> None:
    """Payment amount comes from the stored quote; refuse if it expired, changed, or still needs approval."""
    if presented_hash != quote.content_hash:
        raise QuoteError("Quote has changed")
    if (now or datetime.now(UTC)) > quote.expires_at:
        raise QuoteError("Quote has expired")
    if quote.needs_approval:
        raise QuoteError("Quote requires approval")
