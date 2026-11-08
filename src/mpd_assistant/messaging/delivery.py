"""Delivery tracking: what the providers report happened to a message after we handed it over.

Only masked targets are stored. A receipt that says a message failed becomes a dead-letter entry that staff can see;
a delivered receipt only moves a counter.
"""

import re
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Dict, List

from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.messaging.models import Channel, mask
from mpd_assistant.observability.metrics import MESSAGE_DELIVERY

RECEIPT_TTL_SECONDS = 7 * 24 * 3600
DEAD_LETTER_SLOTS = 200
DEAD_LETTER_TTL_SECONDS = 30 * 24 * 3600

_TWILIO_FAILED = frozenset({"failed", "undelivered", "canceled"})
_TWILIO_OK = frozenset({"delivered", "read"})
_SENDGRID_FAILED = frozenset({"bounce", "dropped", "blocked", "spamreport"})
_SENDGRID_OK = frozenset({"delivered"})


class DeliveryTracker:
    def __init__(self, kv: KeyValueStore, clock: Callable[[], float] = time.time):
        self._kv, self._clock = kv, clock

    # --- recording what we sent -------------------------------------------------------------
    def sent(self, provider_id: str | None, channel: Channel, to: str, template: str, purpose: str) -> None:
        if not provider_id:
            return
        self._kv.set(
            f"deliv:{provider_id}",
            {"channel": channel.value, "to": mask(to), "template": template, "purpose": purpose, "sent_at": self._clock(), "status": "sent"},
            RECEIPT_TTL_SECONDS,
        )

    # --- receipts ---------------------------------------------------------------------------
    def twilio_status(self, form: Mapping[str, str]) -> str:
        """Handles a Twilio status callback. Returns delivered | failed | pending | ignored."""
        sid, status = form.get("MessageSid") or form.get("SmsSid") or "", (form.get("MessageStatus") or form.get("SmsStatus") or "").lower()
        if not sid or not status:
            return "ignored"
        return self._receipt(sid, status, form.get("ErrorCode") or "", _TWILIO_OK, _TWILIO_FAILED, default_channel=Channel.SMS)

    def sendgrid_events(self, events: Iterable[Mapping[str, Any]]) -> int:
        """Handles a SendGrid event-webhook batch. Returns how many events were understood."""
        handled = 0
        for event in events:
            if not isinstance(event, Mapping):
                continue
            sid = str(event.get("sg_message_id", "")).split(".")[0]
            kind = str(event.get("event", "")).lower()
            if not sid or not kind:
                continue
            outcome = self._receipt(sid, kind, str(event.get("reason", ""))[:80], _SENDGRID_OK, _SENDGRID_FAILED, default_channel=Channel.EMAIL)
            handled += outcome != "ignored"
        return handled

    def _receipt(self, provider_id: str, status: str, code: str, ok: frozenset, failed: frozenset, default_channel: Channel) -> str:
        record: Dict[str, Any] = self._kv.get(f"deliv:{provider_id}") or {}
        channel = record.get("channel") or default_channel.value
        if status in ok:
            outcome = "delivered"
        elif status in failed:
            outcome = "failed"
        else:
            outcome = "pending"  # queued, sent, deferred: the provider is still working
        MESSAGE_DELIVERY.labels(channel, outcome).inc()
        if record:
            record["status"] = outcome
            self._kv.set(f"deliv:{provider_id}", record, RECEIPT_TTL_SECONDS)
        if outcome == "failed":
            self._dead_letter(channel, record, status, code)
        return outcome

    # --- dead letters -----------------------------------------------------------------------
    def _dead_letter(self, channel: str, record: Dict[str, Any], status: str, code: str) -> None:
        slot = self._kv.incr("deadletter:counter", DEAD_LETTER_TTL_SECONDS) % DEAD_LETTER_SLOTS
        self._kv.set(
            f"deadletter:{slot}",
            {"at": self._clock(), "channel": channel, "to": record.get("to", "unknown"), "template": record.get("template", "unknown"), "status": status, "code": code},
            DEAD_LETTER_TTL_SECONDS,
        )

    def dead_letters(self, limit: int = 50) -> List[Dict[str, Any]]:
        items = [self._kv.get(f"deadletter:{i}") for i in range(DEAD_LETTER_SLOTS)]
        return sorted((i for i in items if i), key=lambda i: i["at"], reverse=True)[:limit]


_TRANSIENT = re.compile(r"^(twilio|sendgrid)_(5\d\d|429)(_|$)")


def transient(reason: str) -> bool:
    """Failures worth retrying now: network trouble, provider 5xx, or provider rate limiting."""
    return reason.startswith("network_") or bool(_TRANSIENT.match(reason))
