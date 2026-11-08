"""Customer companies: idempotent upsert by normalised name, linked to the person who mentioned it."""

import re
from typing import Protocol

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.models import Company, User

MAX_NAME = 200
_SPACES = re.compile(r"\s+")


def name_key(name: str) -> str:
    return _SPACES.sub(" ", name.strip()).lower()[:MAX_NAME]


def clean_name(name: object) -> str | None:
    if not isinstance(name, str):
        return None
    cleaned = _SPACES.sub(" ", name.strip())[:MAX_NAME]
    return cleaned if len(cleaned) >= 2 else None


class CompanyRepository(Protocol):
    def link_user(self, user_id: str, name: str) -> None: ...


class MemoryCompanyRepository:
    def __init__(self):
        self.by_user: dict[str, str] = {}

    def link_user(self, user_id: str, name: str) -> None:
        cleaned = clean_name(name)
        if cleaned:
            self.by_user[user_id] = cleaned


class SqlCompanyRepository:
    def __init__(self, engine: Engine, tenant_id: str):
        self._engine, self._tenant = engine, tenant_id

    def link_user(self, user_id: str, name: str) -> None:
        cleaned = clean_name(name)
        if not cleaned or not user_id:
            return
        key = name_key(cleaned)
        for _ in range(2):  # a concurrent insert of the same company makes the second pass find it
            with DbSession(self._engine) as db:
                company = db.scalar(select(Company).where(Company.tenant_id == self._tenant, Company.name_key == key))
                if company is None:
                    company = Company(tenant_id=self._tenant, name=cleaned, name_key=key)
                    db.add(company)
                    try:
                        db.flush()
                    except IntegrityError:
                        db.rollback()
                        continue
                user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == self._tenant))
                if user is not None:
                    user.company_id = company.id
                db.commit()
                return
