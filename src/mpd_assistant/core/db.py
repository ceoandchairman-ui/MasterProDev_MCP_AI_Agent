"""Synchronous SQLAlchemy engine helpers shared by the SQL repositories."""

import logging
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.models import Tenant
from mpd_assistant.core.resilience import retry_sync

logger = logging.getLogger(__name__)

DEFAULT_TENANT = "masterprodev"


def make_engine(database_url: str, pool_size: int = 5, max_overflow: int = 5, statement_timeout_ms: int = 15000) -> Engine:
    """Postgres engine. Connections are retried with backoff (a Postgres restart takes seconds), stale pooled connections
    are detected before use, and the pool is bounded. Size it so that replicas x (pool_size + max_overflow) stays under
    the server's max_connections; put PgBouncer in front before raising it past that."""
    url = database_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgres://", "postgresql://")
    if url.startswith("sqlite"):
        return create_engine(url)

    def connect():
        import psycopg2

        options = f"-c statement_timeout={statement_timeout_ms}" if statement_timeout_ms else None  # a stuck query ends instead of holding a connection
        return retry_sync(lambda: psycopg2.connect(url, connect_timeout=5, options=options), attempts=3, base_delay=0.3, retry_on=(psycopg2.OperationalError,))

    return create_engine(url, creator=connect, pool_pre_ping=True, pool_size=pool_size, max_overflow=max_overflow, pool_recycle=1800, pool_timeout=5)


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


def to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def to_epoch(value: datetime | None) -> float | None:
    value = to_utc(value)
    return value.timestamp() if value else None


def from_epoch(value: float | None) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value is not None else None
