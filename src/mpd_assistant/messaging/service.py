"""NotificationService: the one place every outbound message passes through."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Dict, Iterable

from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.messaging.delivery import transient
from mpd_assistant.messaging.models import Channel, OutboundMessage, Provider, Purpose, SendResult
from mpd_assistant.observability.metrics import MESSAGE_RETRIES, MESSAGES
from mpd_assistant.responses.engine import TemplateNotFound, render

OPT_OUT_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "arret", "arrêt"}
OPT_IN_WORDS = {"start", "unstop", "yes", "oui"}


def classify_keyword(text: str) -> str | None:
    word = (text or "").strip().lower()
    if word in OPT_OUT_WORDS:
        return "opt_out"
    if word in OPT_IN_WORDS and word != "yes" and word != "oui":
        return "opt_in"
    return None


class NotificationService:
    def __init__(
        self,
        providers: Iterable[Provider],
        kv: KeyValueStore,
        *,
        per_target_per_hour: int = 5,
        daily_cap_per_channel: int = 500,
        has_consent: Callable[[str | None], bool] = lambda user_id: False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        tracker=None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        retry_delays: Sequence[float] = (0.5, 1.5),
    ):
        self._tracker, self._sleep, self._retry_delays = tracker, sleep, tuple(retry_delays)
        self._by_channel: Dict[Channel, Provider] = {}
        for p in providers:
            for ch in p.channels:
                self._by_channel[ch] = p
        self._kv = kv
        self._per_target = per_target_per_hour
        self._daily_cap = daily_cap_per_channel
        self._has_consent = has_consent
        self._clock = clock

    def has_channel(self, channel: Channel) -> bool:
        return channel in self._by_channel

    # --- opt-out registry ---------------------------------------------------
    def record_opt_out(self, channel: Channel, to: str) -> None:
        self._kv.set(f"optout:{channel.value}:{to}", True, 10 * 365 * 86400)

    def clear_opt_out(self, channel: Channel, to: str) -> None:
        self._kv.delete(f"optout:{channel.value}:{to}")

    def is_opted_out(self, channel: Channel, to: str) -> bool:
        return bool(self._kv.get(f"optout:{channel.value}:{to}"))

    # --- sending -------------------------------------------------------------
    def _block(self, msg: OutboundMessage, reason: str) -> SendResult:
        MESSAGES.labels(msg.channel.value, msg.purpose.value, "blocked").inc()
        return SendResult("blocked", reason=reason)

    async def send(self, msg: OutboundMessage) -> SendResult:
        provider = self._by_channel.get(msg.channel)
        if provider is None:
            MESSAGES.labels(msg.channel.value, msg.purpose.value, "failed").inc()
            return SendResult("failed", reason="no_provider")

        if msg.idempotency_key:
            prior = self._kv.get(f"idem:{msg.idempotency_key}")
            if prior:
                return SendResult("skipped", provider_id=prior.get("provider_id"), reason="duplicate")

        if msg.purpose is Purpose.MARKETING:
            if self.is_opted_out(msg.channel, msg.to):
                return self._block(msg, "opted_out")
            if not self._has_consent(msg.user_id):
                return self._block(msg, "no_consent")

        if self._kv.incr(f"rate:{msg.channel.value}:{msg.to}", 3600) > self._per_target:
            return self._block(msg, "rate_limited")
        day = self._clock().strftime("%Y%m%d")
        if self._kv.incr(f"cap:{msg.channel.value}:{day}", 86400) > self._daily_cap:
            return self._block(msg, "daily_cap")

        if msg.body is not None:
            body = msg.body
        else:
            try:
                body = render(msg.template, msg.locale, msg.variables)
            except TemplateNotFound:
                return SendResult("failed", reason="unknown_template")
        subject = msg.subject
        if subject is None and msg.channel is Channel.EMAIL and msg.body is None:
            try:
                subject = render(f"{msg.template}_subject", msg.locale, msg.variables)
            except TemplateNotFound:
                subject = None

        result = await provider.send(msg.channel, msg.to, body, subject)
        for delay in self._retry_delays:  # transient provider trouble is retried a couple of times with a growing pause
            if result.status != "failed" or not transient(result.reason):
                break
            MESSAGE_RETRIES.labels(msg.channel.value).inc()
            await self._sleep(delay)
            result = await provider.send(msg.channel, msg.to, body, subject)
        MESSAGES.labels(msg.channel.value, msg.purpose.value, result.status).inc()
        if result.status == "sent" and self._tracker is not None:
            self._tracker.sent(result.provider_id, msg.channel, msg.to, msg.template, msg.purpose.value)
        if result.status == "sent" and msg.idempotency_key:
            self._kv.set(f"idem:{msg.idempotency_key}", {"provider_id": result.provider_id}, 86400)
        return result


class MessengerSender:
    """Adapts the notification service to the identity Sender interface (OTP delivery)."""

    def __init__(self, notifications: NotificationService, channel: Channel, locale: str = "en"):
        self._n, self._channel, self._locale = notifications, channel, locale

    async def send(self, target: str, code: str) -> None:
        result = await self._n.send(
            OutboundMessage(self._channel, target, "otp_code", self._locale, {"code": code}, Purpose.TRANSACTIONAL)
        )
        if result.status not in ("sent", "skipped"):
            raise RuntimeError(f"OTP delivery failed: {result.reason}")
