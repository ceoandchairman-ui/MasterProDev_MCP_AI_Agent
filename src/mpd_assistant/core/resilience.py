"""Small resilience helpers: retries with backoff, a circuit breaker, and a classifier for infrastructure errors.

A dependency that is briefly down (a Postgres restart, a Redis blip, a slow model provider) should cost a user one
polite "please retry" message, not a stack trace, and should not be hammered while it recovers.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Tuple, Type, TypeVar

T = TypeVar("T")


class CircuitOpen(RuntimeError):
    pass


class CircuitBreaker:
    """Opens after `failure_threshold` consecutive failures and rejects calls for `reset_seconds`, then lets one
    probe call through (half-open). A success closes it again."""

    def __init__(self, failure_threshold: int = 5, reset_seconds: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self._threshold, self._reset, self._clock = failure_threshold, reset_seconds, clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None and self._clock() - self._opened_at < self._reset

    def allow(self) -> None:
        if self.is_open:
            raise CircuitOpen("circuit open")
        # past the reset window (or never opened): allow a call; the next result decides the state

    def record_success(self) -> None:
        self._failures, self._opened_at = 0, None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()


def retry_sync(fn: Callable[[], T], attempts: int = 3, base_delay: float = 0.2, retry_on: Tuple[Type[BaseException], ...] = (Exception,), sleep=time.sleep) -> T:
    for attempt in range(attempts):
        try:
            return fn()
        except retry_on:
            if attempt == attempts - 1:
                raise
            sleep(base_delay * (2**attempt))
    raise RuntimeError("unreachable")  # pragma: no cover


async def retry_async(
    fn: Callable[[], Awaitable[T]], attempts: int = 3, base_delay: float = 0.2, retry_on: Tuple[Type[BaseException], ...] = (Exception,), sleep=asyncio.sleep
) -> T:
    for attempt in range(attempts):
        try:
            return await fn()
        except retry_on:
            if attempt == attempts - 1:
                raise
            await sleep(base_delay * (2**attempt))
    raise RuntimeError("unreachable")  # pragma: no cover


_DB_ERROR_MODULES = ("sqlalchemy.exc", "psycopg2", "asyncpg", "sqlite3")
_REDIS_ERROR_MODULES = ("redis",)


def infrastructure_failure(exc: BaseException) -> str | None:
    """'postgres' or 'redis' when the exception is a connection-level failure of that dependency, else None.
    Programming errors (a KeyError, a bad argument) return None so they still surface as bugs."""
    for current in (exc, exc.__cause__, exc.__context__):
        if current is None:
            continue
        module = type(current).__module__
        name = type(current).__name__
        if module.startswith(_REDIS_ERROR_MODULES) and ("Connection" in name or "Timeout" in name or "Busy" in name or "Response" in name):
            return "redis"
        if module.startswith(_DB_ERROR_MODULES) and any(k in name for k in ("Operational", "Interface", "DBAPI", "Timeout", "Connection", "Disconnect")):
            return "postgres"
    return None


__all__ = ["CircuitBreaker", "CircuitOpen", "infrastructure_failure", "retry_async", "retry_sync"]
