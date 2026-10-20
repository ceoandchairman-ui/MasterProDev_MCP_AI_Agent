"""Escalation records, the minimum-necessary handover packet for staff, and the staff alert."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Dict, List, Protocol

from mpd_assistant.graph.handoff import build_packet
from mpd_assistant.memory.short_term.window import Message
from mpd_assistant.messaging.models import Channel, OutboundMessage, Purpose
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
    is_new: bool = field(default=False, repr=False)


class Notifier(Protocol):
    def notify(self, escalation: Escalation) -> None: ...


class EscalationRepository(Protocol):
    def open_for_session(self, session_id: str) -> Escalation | None: ...
    def save(self, escalation: Escalation) -> None: ...
    def get(self, reference: str) -> Escalation | None: ...
    def list_open(self) -> List[Escalation]: ...


class InMemoryEscalations:
    def __init__(self):
        self._by_ref: Dict[str, Escalation] = {}

    def open_for_session(self, session_id: str) -> Escalation | None:
        return next((e for e in self._by_ref.values() if e.session_id == session_id and e.status == "open"), None)

    def save(self, escalation: Escalation) -> None:
        self._by_ref[escalation.reference] = escalation

    def get(self, reference: str) -> Escalation | None:
        return self._by_ref.get(reference)

    def list_open(self) -> List[Escalation]:
        return [e for e in self._by_ref.values() if e.status == "open"]


def build_summary(messages: List[Message]) -> str:
    """Recent turns with personal data masked; staff see contact details only through the user record."""
    turns = [m for m in messages if m.get("role") in ("user", "assistant")][-MAX_SUMMARY_TURNS:]
    return "\n".join(f"{m['role']}: {redact(str(m.get('content', '')))[:300]}" for m in turns)


class EscalationService:
    def __init__(self, notifier: Notifier | None = None, repo: EscalationRepository | None = None):
        self._notifier = notifier
        self._repo: EscalationRepository = repo or InMemoryEscalations()

    def raise_escalation(self, session_id: str, reason: str, messages: List[Message], reference: str | None = None) -> Escalation:
        existing = self._repo.open_for_session(session_id)
        if existing:
            return existing  # one open escalation per session; the bot stays paused
        esc = Escalation(reference or uuid.uuid4().hex[:8].upper(), session_id, reason, build_summary(messages), is_new=True)
        self._repo.save(esc)
        if self._notifier is not None:
            self._notifier.notify(esc)
        return esc

    def update(self, escalation: Escalation) -> None:
        self._repo.save(escalation)

    def is_paused(self, session_id: str) -> bool:
        return self._repo.open_for_session(session_id) is not None

    def open_reference(self, session_id: str) -> str | None:
        esc = self._repo.open_for_session(session_id)
        return esc.reference if esc else None

    def resolve(self, reference: str) -> bool:
        esc = self._repo.get(reference)
        if esc is None or esc.status != "open":
            return False
        esc.status = "resolved"
        self._repo.save(esc)
        return True


class EscalationFlow:
    """Glue used by the graph: record the escalation, alert staff once, return the reference for the user."""

    def __init__(self, service: EscalationService, notifications, staff_email: str | None):
        self._service, self._notifications, self._staff_email = service, notifications, staff_email

    async def hook(self, state, reason: str) -> str | None:
        session_id = state.get("session_row") or state.get("session_id") or ""
        esc = self._service.raise_escalation(session_id, reason, state.get("messages", []))
        if esc.is_new:
            packet = build_packet(state)
            if packet:
                esc.summary = f"{packet}\n\n{esc.summary}"
                self._service.update(esc)
        if esc.is_new and self._staff_email and self._notifications is not None:
            await self._notifications.send(
                OutboundMessage(
                    Channel.EMAIL,
                    self._staff_email,
                    "escalation_staff",
                    "en",
                    {"reference": esc.reference, "reason": reason, "summary": esc.summary},
                    Purpose.TRANSACTIONAL,
                    idempotency_key=f"escalation:{esc.reference}",
                )
            )
        return esc.reference

    def is_paused(self, session_id: str) -> bool:
        return self._service.is_paused(session_id)

    def open_reference(self, session_id: str) -> str | None:
        return self._service.open_reference(session_id)
