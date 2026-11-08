"""Turn persistence. Stores the pseudonymized user text and the reply, never the raw message."""

from sqlalchemy import Engine
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.models import Turn


class SqlTurnRecorder:
    def __init__(self, engine: Engine):
        self._engine = engine

    def record(self, session_id: str, user_text: str, reply: str, intent: str, agent: str, mode: str, trace_id: str | None = None) -> None:
        with DbSession(self._engine) as db:
            db.add(
                Turn(
                    session_id=session_id,
                    user_text=user_text[:4000],
                    reply_text=reply[:8000],
                    intent=intent or None,
                    agent=agent or None,
                    mode=mode or None,
                    trace_id=trace_id,
                )
            )
            db.commit()
