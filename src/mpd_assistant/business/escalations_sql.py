from typing import List

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.business.escalations import Escalation
from mpd_assistant.core.db import to_utc
from mpd_assistant.core.models import Escalation as EscalationRow


def _to_domain(row: EscalationRow) -> Escalation:
    return Escalation(row.reference, row.session_id, row.reason, row.summary, row.status, to_utc(row.created_at))


class SqlEscalationRepository:
    """Open escalations pause the bot for that session on every replica."""

    def __init__(self, engine: Engine):
        self._engine = engine

    def open_for_session(self, session_id: str) -> Escalation | None:
        with DbSession(self._engine) as db:
            row = db.scalar(select(EscalationRow).where(EscalationRow.session_id == session_id, EscalationRow.status == "open"))
            return _to_domain(row) if row else None

    def save(self, escalation: Escalation) -> None:
        with DbSession(self._engine) as db:
            row = db.scalar(select(EscalationRow).where(EscalationRow.reference == escalation.reference))
            if row is None:
                row = EscalationRow(reference=escalation.reference, session_id=escalation.session_id)
                db.add(row)
            row.reason, row.summary, row.status = escalation.reason, escalation.summary, escalation.status
            db.commit()

    def get(self, reference: str) -> Escalation | None:
        with DbSession(self._engine) as db:
            row = db.scalar(select(EscalationRow).where(EscalationRow.reference == reference))
            return _to_domain(row) if row else None

    def list_open(self) -> List[Escalation]:
        with DbSession(self._engine) as db:
            return [_to_domain(r) for r in db.scalars(select(EscalationRow).where(EscalationRow.status == "open"))]
