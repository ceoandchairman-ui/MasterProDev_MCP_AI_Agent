"""Synchronous SQLAlchemy engine helpers shared by the SQL repositories."""

import logging
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.models import Tenant

logger = logging.getLogger(__name__)

DEFAULT_TENANT = "masterprodev"


def make_engine(database_url: str) -> Engine:
    url = database_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgres://", "postgresql://")
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, connect_args={"connect_timeout": 5}) if not url.startswith("sqlite") else create_engine(url)


def check_engine(engine: Engine) -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


def ensure_tenant(engine: Engine, name: str = DEFAULT_TENANT) -> str:
    with DbSession(engine) as db:
        tenant = db.scalar(select(Tenant).where(Tenant.name == name))
        if tenant is None:
            tenant = Tenant(name=name)
            db.add(tenant)
            db.commit()
        return tenant.id


def to_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def to_epoch(value: Optional[datetime]) -> Optional[float]:
    value = to_utc(value)
    return value.timestamp() if value else None


def from_epoch(value: Optional[float]) -> Optional[datetime]:
    return datetime.fromtimestamp(value, UTC) if value is not None else None
