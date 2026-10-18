"""Escalation records and the minimum-necessary handover packet for staff."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Dict, List, Protocol

from mpd_assistant.memory.short_term.window import Message
from mpd_assistant.privacy.detector import redact

MAX_SUMMARY_TURNS = 6


@dataclass
class Escalation:
    reference: str
    session_id: str
    reason: str
    summary: str
    status: str = "open"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class Notifier(Protocol):
    def notify(self, escalation: Escalation) -> None: ...


def build_summary(messages: List[Message]) -> str:
    """Recent turns with personal data masked; staff see contact details only through the user record."""
    turns = [m for m in messages if m.get("role") in ("user", "assistant")][-MAX_SUMMARY_TURNS:]
    return "\n".join(f"{m['role']}: {redact(str(m.get('content', '')))[:300]}" for m in turns)


class EscalationService:
    def __init__(self, notifier: Notifier):
        self._notifier = notifier
        self._open: Dict[str, Escalation] = {}

    def raise_escalation(self, session_id: str, reason: str, messages: List[Message], reference: str | None = None) -> Escalation:
        existing = next((e for e in self._open.values() if e.session_id == session_id and e.status == "open"), None)
        if existing:
            return existing  # one open escalation per session; the bot stays paused
        esc = Escalation(reference or uuid.uuid4().hex[:8].upper(), session_id, reason, build_summary(messages))
        self._open[esc.reference] = esc
        self._notifier.notify(esc)
        return esc

    def is_paused(self, session_id: str) -> bool:
        return any(e.session_id == session_id and e.status == "open" for e in self._open.values())

    def resolve(self, reference: str) -> bool:
        esc = self._open.get(reference)
        if esc is None or esc.status != "open":
            return False
        esc.status = "resolved"
        return True
