from typing import Optional

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.db import from_epoch, to_epoch
from mpd_assistant.core.models import Session as SessionRow
from mpd_assistant.sessions.service import Session


def _to_domain(row: SessionRow) -> Session:
    return Session(
        id=row.id,
        thread_id=row.thread_id,
        user_id=row.user_id,
        created_at=to_epoch(row.created_at) or 0.0,
        last_seen=to_epoch(row.last_seen_at) or 0.0,
        verified=row.verified,
        revoked=row.revoked_at is not None,
    )


class SqlSessionRepository:
    """Postgres is the source of truth for sessions; any API replica can resume any session."""

    def __init__(self, engine: Engine, tenant_id: str):
        self._engine, self._tenant = engine, tenant_id

    def get(self, session_id: str) -> Optional[Session]:
        with DbSession(self._engine) as db:
            row = db.get(SessionRow, session_id)
            return _to_domain(row) if row else None

    def save(self, session: Session) -> None:
        with DbSession(self._engine) as db:
            row = db.get(SessionRow, session.id)
            if row is None:
                row = SessionRow(id=session.id, thread_id=session.thread_id, tenant_id=self._tenant)
                db.add(row)
            row.user_id = session.user_id
            row.verified = session.verified
            row.created_at = from_epoch(session.created_at)
            row.last_seen_at = from_epoch(session.last_seen)
            row.revoked_at = from_epoch(session.last_seen) if session.revoked else None
            db.commit()

    def for_user(self, user_id: str) -> list:
        with DbSession(self._engine) as db:
            return [_to_domain(r) for r in db.scalars(select(SessionRow).where(SessionRow.user_id == user_id))]
