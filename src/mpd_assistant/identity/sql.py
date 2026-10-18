from typing import Optional

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.db import to_utc
from mpd_assistant.core.models import User
from mpd_assistant.identity.service import VerifiedUser


def _to_domain(row: User) -> VerifiedUser:
    return VerifiedUser(row.id, row.name_enc, row.email_enc, row.email_index, row.phone_enc, row.phone_index, to_utc(row.email_verified_at))


class SqlUserRepository:
    """Contact fields are stored encrypted; lookups use keyed blind indexes."""

    def __init__(self, engine: Engine, tenant_id: str):
        self._engine, self._tenant = engine, tenant_id

    def _one(self, *conditions) -> Optional[VerifiedUser]:
        with DbSession(self._engine) as db:
            row = db.scalar(select(User).where(User.tenant_id == self._tenant, User.deleted_at.is_(None), *conditions))
            return _to_domain(row) if row else None

    def find_by_email_index(self, index: str) -> Optional[VerifiedUser]:
        return self._one(User.email_index == index)

    def find_by_phone_index(self, index: str) -> Optional[VerifiedUser]:
        return self._one(User.phone_index == index)

    def find_by_id(self, user_id: str) -> Optional[VerifiedUser]:
        return self._one(User.id == user_id)

    def update_contact(self, user_id: str, **fields) -> None:
        allowed = {"name_enc", "email_enc", "email_index", "phone_enc", "phone_index"}
        with DbSession(self._engine) as db:
            row = db.get(User, user_id)
            if row is None:
                return
            for name, value in fields.items():
                if name in allowed:
                    setattr(row, name, value)
            db.commit()

    def memory_consent(self, user_id: str) -> bool:
        with DbSession(self._engine) as db:
            row = db.get(User, user_id)
            return bool(row and row.memory_consent)

    def set_memory_consent(self, user_id: str, enabled: bool) -> None:
        with DbSession(self._engine) as db:
            row = db.get(User, user_id)
            if row is not None:
                row.memory_consent = enabled
                db.commit()

    def save(self, user: VerifiedUser) -> None:
        with DbSession(self._engine) as db:
            row = db.get(User, user.id) or User(id=user.id, tenant_id=self._tenant)
            row.name_enc, row.email_enc, row.email_index = user.name_enc, user.email_enc, user.email_index
            row.phone_enc, row.phone_index = user.phone_enc, user.phone_index
            row.email_verified_at = row.phone_verified_at = user.verified_at
            db.add(row)
            db.commit()
