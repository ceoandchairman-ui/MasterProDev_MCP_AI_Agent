"""Conversation retention: delete old turns, tool-call records and sessions. Windows are placeholders until the
business sets them (see docs/privacy/data-map.md). Sessions tied to an escalation are kept for the follow-up."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, delete, exists, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.models import Escalation, Session, ToolCall, Turn


@dataclass
class RetentionReport:
    sessions: int = 0
    turns: int = 0
    tool_calls: int = 0


def purge_conversations(engine: Engine, *, user_days: int, guest_days: int, now: datetime | None = None) -> RetentionReport:
    now = now or datetime.now(UTC)
    user_cutoff, guest_cutoff = now - timedelta(days=user_days), now - timedelta(days=guest_days)
    report = RetentionReport()
    with DbSession(engine) as db:
        expired = select(Session.id).where(
            ((Session.user_id.is_(None)) & (Session.last_seen_at < guest_cutoff))
            | ((Session.user_id.is_not(None)) & (Session.last_seen_at < user_cutoff)),
            ~exists().where(Escalation.session_id == Session.id),
        )
        ids = list(db.scalars(expired))
        for start in range(0, len(ids), 500):
            batch = ids[start : start + 500]
            report.tool_calls += db.execute(delete(ToolCall).where(ToolCall.session_id.in_(batch))).rowcount or 0
            report.turns += db.execute(delete(Turn).where(Turn.session_id.in_(batch))).rowcount or 0
            report.sessions += db.execute(delete(Session).where(Session.id.in_(batch))).rowcount or 0
        db.commit()
    return report


__all__ = ["RetentionReport", "purge_conversations"]
