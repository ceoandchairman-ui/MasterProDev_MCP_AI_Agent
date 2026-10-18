import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from mpd_assistant.business.escalations import EscalationService, build_summary
from mpd_assistant.business.quoting import CatalogItem, QuoteError, build_quote, verify_quote_for_payment
from mpd_assistant.cache.store import MemoryBackend, RedisBackend, ResponseCache

CATALOG = {
    "dev-hour": CatalogItem("dev-hour", "Development hour", "hour", 15000),
    "audit": CatalogItem("audit", "Architecture audit", "fixed", 500000),
}


# --- cache ------------------------------------------------------------------
async def test_cache_hit_miss_and_ttl():
    t = [0.0]
    cache = ResponseCache(MemoryBackend(clock=lambda: t[0]))
    assert await cache.get("k") is None
    await cache.set("k", "v", ttl=10)
    assert await cache.get("k") == "v"
    t[0] = 11
    assert await cache.get("k") is None


async def test_single_flight_runs_compute_once():
    cache = ResponseCache(MemoryBackend())
    calls = []

    async def compute():
        calls.append(1)
        await asyncio.sleep(0.05)
        return "answer", True

    results = await asyncio.gather(*[cache.get_or_compute("q", compute, 60) for _ in range(10)])
    assert results == ["answer"] * 10 and len(calls) == 1


async def test_uncacheable_results_are_not_stored_and_errors_propagate():
    cache = ResponseCache(MemoryBackend())

    async def compute():
        return "x", False

    assert await cache.get_or_compute("k", compute, 60) == "x"
    assert await cache.get("k") is None

    async def boom():
        raise RuntimeError("llm down")

    with pytest.raises(RuntimeError):
        await cache.get_or_compute("k2", boom, 60)
    assert await cache.get_or_compute("k2", compute, 60) == "x"  # failure did not poison the key


async def test_invalidate_prefix():
    cache = ResponseCache(MemoryBackend())
    await cache.set("resp:a", "1", 60)
    await cache.set("other:b", "2", 60)
    assert await cache.invalidate("resp:") == 1
    assert await cache.get("other:b") == "2"


async def test_redis_failure_degrades_to_miss():
    class Broken:
        async def get(self, k):
            raise ConnectionError

        async def set(self, *a, **k):
            raise ConnectionError

    cache = ResponseCache(RedisBackend(Broken()))
    assert await cache.get("k") is None
    await cache.set("k", "v", 10)  # must not raise


# --- quoting ----------------------------------------------------------------
def test_quote_is_priced_by_code():
    q = build_quote(CATALOG, [{"sku": "dev-hour", "quantity": 40}, {"sku": "audit", "quantity": 1}])
    assert q.subtotal_cents == 40 * 15000 + 500000
    assert q.tax_cents == round(q.subtotal_cents * 0.13)
    assert q.total_cents == q.subtotal_cents + q.tax_cents and not q.needs_approval


def test_quote_rejects_bad_input():
    for bad in ([], [{"sku": "nope", "quantity": 1}], [{"sku": "audit", "quantity": 0}], [{"sku": "audit", "quantity": -3}], [{"sku": "audit", "quantity": "abc"}]):
        with pytest.raises(QuoteError):
            build_quote(CATALOG, bad)


def test_large_quote_needs_approval_and_blocks_payment():
    q = build_quote(CATALOG, [{"sku": "dev-hour", "quantity": 400}])
    assert q.needs_approval
    with pytest.raises(QuoteError, match="approval"):
        verify_quote_for_payment(q, q.content_hash)


def test_payment_verification_checks_hash_and_expiry():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    q = build_quote(CATALOG, [{"sku": "audit", "quantity": 1}], now=now)
    verify_quote_for_payment(q, q.content_hash, now=now)
    with pytest.raises(QuoteError, match="changed"):
        verify_quote_for_payment(q, "deadbeef", now=now)
    with pytest.raises(QuoteError, match="expired"):
        verify_quote_for_payment(q, q.content_hash, now=now + timedelta(days=31))


def test_fractional_quantities_round_half_up():
    cat = {"x": CatalogItem("x", "X", "hour", 333)}
    assert build_quote(cat, [{"sku": "x", "quantity": Decimal("1.5")}]).lines[0].total_cents == 500


# --- escalations ------------------------------------------------------------
class Capture:
    def __init__(self):
        self.sent = []

    def notify(self, esc):
        self.sent.append(esc)


def test_escalation_summary_masks_pii_and_limits_turns():
    msgs = [{"role": "user", "content": f"m{i} write to ann@example.com"} for i in range(10)]
    summary = build_summary(msgs)
    assert "ann@example.com" not in summary and summary.count("\n") == 5


def test_one_open_escalation_per_session_and_bot_pauses():
    n = Capture()
    svc = EscalationService(n)
    first = svc.raise_escalation("s1", "human_request", [{"role": "user", "content": "help"}])
    again = svc.raise_escalation("s1", "complaint", [])
    assert again.reference == first.reference and len(n.sent) == 1
    assert svc.is_paused("s1") and not svc.is_paused("s2")
    assert svc.resolve(first.reference) and not svc.is_paused("s1")
    assert not svc.resolve(first.reference)
