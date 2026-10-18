"""Session lifecycle: idle and absolute timeouts, revocation that sticks, per-user revoke-all."""

import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Protocol

IDLE_TIMEOUT_SECONDS = 30 * 60
ABSOLUTE_TIMEOUT_SECONDS = 24 * 3600


@dataclass
class Session:
    id: str
    thread_id: str
    user_id: Optional[str]
    created_at: float
    last_seen: float
    verified: bool = False
    revoked: bool = False


class SessionRepository(Protocol):
    def get(self, session_id: str) -> Optional[Session]: ...
    def save(self, session: Session) -> None: ...
    def for_user(self, user_id: str) -> list: ...


class MemorySessionRepository:
    def __init__(self):
        self._rows: Dict[str, Session] = {}

    def get(self, session_id: str) -> Optional[Session]:
        return self._rows.get(session_id)

    def save(self, session: Session) -> None:
        self._rows[session.id] = session

    def for_user(self, user_id: str) -> list:
        return [s for s in self._rows.values() if s.user_id == user_id]


class SessionService:
    def __init__(self, repo: SessionRepository, clock: Callable[[], float] = time.time):
        self._repo = repo
        self._clock = clock

    def create(self, user_id: Optional[str] = None, verified: bool = False) -> Session:
        now = self._clock()
        session = Session(uuid.uuid4().hex, uuid.uuid4().hex, user_id, now, now, verified)
        self._repo.save(session)
        return session

    def resume(self, session_id: str) -> Optional[Session]:
        """Return a live session and refresh its idle timer, or None if unknown, revoked or expired."""
        session = self._repo.get(session_id)
        if session is None or session.revoked:
            return None
        now = self._clock()
        if now - session.last_seen > IDLE_TIMEOUT_SECONDS or now - session.created_at > ABSOLUTE_TIMEOUT_SECONDS:
            session.revoked = True
            self._repo.save(session)
            return None
        session.last_seen = now
        self._repo.save(session)
        return session

    def revoke(self, session_id: str) -> None:
        session = self._repo.get(session_id)
        if session:
            session.revoked = True
            self._repo.save(session)

    def revoke_all_for_user(self, user_id: str) -> int:
        sessions = self._repo.for_user(user_id)
        for s in sessions:
            s.revoked = True
            self._repo.save(s)
        return len(sessions)

    def upgrade_to_verified(self, session_id: str, user_id: str) -> Optional[Session]:
        """A visitor becomes a verified user without losing the thread (and so the history)."""
        session = self.resume(session_id)
        if session is None:
            return None
        session.user_id, session.verified = user_id, True
        self._repo.save(session)
        return session
