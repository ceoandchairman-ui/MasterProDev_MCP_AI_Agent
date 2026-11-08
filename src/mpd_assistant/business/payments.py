"""Payment node (code, not an agent): Stripe-hosted checkout for a stored quote, confirmed only by a signed webhook.

The amount always comes from the stored quote. No card data passes through the chat. A quote is marked paid only
when Stripe's signed webhook says so and the amount and currency match what we stored.
"""

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from mpd_assistant.business.quote_store import PAYABLE, QuoteRepository, StoredQuote
from mpd_assistant.business.quoting import quote_hash
from mpd_assistant.core.kv import KeyValueStore

logger = logging.getLogger(__name__)

STRIPE_API = "https://api.stripe.com/v1"
SIGNATURE_TOLERANCE_SECONDS = 300
EVENT_DEDUP_SECONDS = 7 * 24 * 3600


class PaymentError(RuntimeError):
    pass


class InvalidSignature(PaymentError):
    pass


@dataclass
class CheckoutSession:
    session_id: str
    url: str


class CheckoutProvider(Protocol):
    async def create_session(self, *, quote_id: str, label: str, amount_cents: int, currency: str, idempotency_key: str) -> CheckoutSession: ...


class StripeCheckout:
    def __init__(self, secret_key: str, success_url: str, cancel_url: str, client: httpx.AsyncClient | None = None, timeout: float = 15.0):
        self._key, self._success, self._cancel = secret_key, success_url, cancel_url
        self._client, self._timeout = client, timeout

    async def create_session(self, *, quote_id: str, label: str, amount_cents: int, currency: str, idempotency_key: str) -> CheckoutSession:
        data = {
            "mode": "payment",
            "success_url": self._success,
            "cancel_url": self._cancel,
            "client_reference_id": quote_id,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": str(amount_cents),
            "line_items[0][price_data][product_data][name]": label,
            "metadata[quote_id]": quote_id,
            "payment_intent_data[metadata][quote_id]": quote_id,
        }
        headers = {"Authorization": f"Bearer {self._key}", "Idempotency-Key": idempotency_key}
        url = f"{STRIPE_API}/checkout/sessions"
        try:
            if self._client:
                resp = await self._client.post(url, data=data, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, data=data, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            body = resp.json()
            return CheckoutSession(body["id"], body["url"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise PaymentError(f"Checkout creation failed: {type(exc).__name__}") from exc  # never include key or body


def verify_stripe_signature(payload: bytes, header: str, secret: str, now: float | None = None, tolerance: int = SIGNATURE_TOLERANCE_SECONDS) -> None:
    """Stripe-Signature: t=<unix>,v1=<hex hmac-sha256 of "t.payload">[,v1=...]. Raises InvalidSignature."""
    if not secret or not header:
        raise InvalidSignature("missing signature or secret")
    timestamp, signatures = None, []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures:
        raise InvalidSignature("malformed signature header")
    try:
        age = abs((now if now is not None else time.time()) - int(timestamp))
    except ValueError as exc:
        raise InvalidSignature("bad timestamp") from exc
    if age > tolerance:
        raise InvalidSignature("timestamp outside tolerance")
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in signatures):
        raise InvalidSignature("signature mismatch")


@dataclass
class CheckoutResult:
    ok: bool
    reason: str = ""
    url: str | None = None
    quote: StoredQuote | None = None


@dataclass
class WebhookOutcome:
    status: str  # paid | duplicate | ignored | mismatch | unknown_quote
    quote_ref: str | None = None


QuoteCallback = Callable[[StoredQuote], Awaitable[None]]


class PaymentService:
    def __init__(
        self,
        quotes: QuoteRepository,
        provider: CheckoutProvider | None,
        kv: KeyValueStore,
        webhook_secret: str | None,
        on_paid: QuoteCallback | None = None,
        on_mismatch: QuoteCallback | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._quotes, self._provider, self._kv, self._secret = quotes, provider, kv, webhook_secret
        self._on_paid, self._on_mismatch, self._clock = on_paid, on_mismatch, clock

    @property
    def configured(self) -> bool:
        return self._provider is not None and bool(self._secret)

    def check(self, user_id: str, ref: str | None = None) -> tuple[StoredQuote | None, str]:
        """Guard with no side effects except marking an expired quote. Returns (quote, "") when payable."""
        quote = self._quotes.find_for_user(user_id, ref)
        if quote is None:
            return None, "no_quote"
        if quote.status == "paid":
            return quote, "already_paid"
        if quote.status == "needs_approval":
            return quote, "needs_approval"
        if quote.status not in PAYABLE:
            return quote, "not_payable"
        if quote.expires_at is not None and self._clock() > quote.expires_at:
            self._quotes.set_status(quote.id, "expired")
            return quote, "expired"
        if quote_hash(quote.hash_inputs(), quote.total_cents, quote.currency) != quote.content_hash:
            return quote, "quote_changed"
        if sum(int(x["total_cents"]) for x in quote.lines) > quote.total_cents:
            return quote, "quote_changed"  # total must include every line (plus tax)
        return quote, ""

    async def start_checkout(self, user_id: str, ref: str | None = None) -> CheckoutResult:
        if not self.configured:
            return CheckoutResult(False, "payments_not_configured")
        quote, reason = self.check(user_id, ref)
        if reason:
            return CheckoutResult(False, reason, quote=quote)
        assert quote is not None and self._provider is not None
        try:
            session = await self._provider.create_session(
                quote_id=quote.id,
                label=f"MasterProDev quote {quote.ref}",
                amount_cents=quote.total_cents,
                currency=quote.currency,
                idempotency_key=f"checkout-{quote.id}-{quote.content_hash[:16]}",
            )
        except PaymentError:
            logger.warning("checkout creation failed for quote %s", quote.ref)
            return CheckoutResult(False, "provider_error", quote=quote)
        self._quotes.set_status(quote.id, "accepted")
        return CheckoutResult(True, url=session.url, quote=quote)

    async def handle_webhook(self, payload: bytes, signature_header: str) -> WebhookOutcome:
        verify_stripe_signature(payload, signature_header, self._secret or "")
        try:
            event = json.loads(payload)
        except ValueError as exc:
            raise InvalidSignature("payload is not JSON") from exc
        if event.get("type") not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            return WebhookOutcome("ignored")
        session = (event.get("data") or {}).get("object") or {}
        if session.get("payment_status") != "paid":
            return WebhookOutcome("ignored")

        dedup = f"stripe:event:{event.get('id', '')}"
        if self._kv.incr(dedup, EVENT_DEDUP_SECONDS) > 1:
            return WebhookOutcome("duplicate")
        try:
            quote_id = session.get("client_reference_id") or (session.get("metadata") or {}).get("quote_id") or ""
            quote = self._quotes.get(quote_id)
            if quote is None:
                logger.warning("payment webhook for an unknown quote")
                return WebhookOutcome("unknown_quote")
            if quote.status == "paid":
                return WebhookOutcome("duplicate", quote.ref)
            amount_ok = int(session.get("amount_total") or -1) == quote.total_cents
            currency_ok = str(session.get("currency") or "").lower() == quote.currency.lower()
            if not (amount_ok and currency_ok):
                self._quotes.set_status(quote.id, "payment_review")
                logger.error("payment amount or currency mismatch for quote %s", quote.ref)
                if self._on_mismatch:
                    await self._on_mismatch(quote)
                return WebhookOutcome("mismatch", quote.ref)
            self._quotes.set_status(quote.id, "paid")
            if self._on_paid:
                try:
                    await self._on_paid(quote)
                except Exception:
                    logger.exception("payment receipt failed for quote %s", quote.ref)  # payment stands either way
            return WebhookOutcome("paid", quote.ref)
        except Exception:
            self._kv.delete(dedup)  # let Stripe's retry try again
            raise


__all__ = [
    "CheckoutResult",
    "InvalidSignature",
    "PaymentError",
    "PaymentService",
    "StripeCheckout",
    "WebhookOutcome",
    "verify_stripe_signature",
]
