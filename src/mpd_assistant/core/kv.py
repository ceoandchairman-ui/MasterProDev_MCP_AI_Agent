"""Small key-value store abstraction (JSON values with TTL): memory for tests, Redis for deployments."""

import json
import time
from collections.abc import Callable
from typing import Any, Dict, Optional, Protocol, Tuple


class KeyValueStore(Protocol):
    def get(self, key: str) -> Optional[Any]: ...
    def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...
    def delete(self, key: str) -> None: ...
    def incr(self, key: str, ttl_seconds: int) -> int: ...


class MemoryKV:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._data: Dict[str, Tuple[str, float]] = {}
        self._clock = clock

    def get(self, key: str) -> Optional[Any]:
        item = self._data.get(key)
        if item is None:
            return None
        if item[1] < self._clock():
            del self._data[key]
            return None
        return json.loads(item[0])

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._data[key] = (json.dumps(value), self._clock() + ttl_seconds)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def incr(self, key: str, ttl_seconds: int) -> int:
        current = self.get(key) or 0
        item = self._data.get(key)
        expires = item[1] if item else self._clock() + ttl_seconds
        self._data[key] = (json.dumps(current + 1), expires)
        return current + 1


class BestEffortKV:
    """For state that is nice to have but must never break a turn (conversation summaries, entity notes, topic tracking).

    If the underlying store fails, reads return nothing and writes are dropped. After repeated failures it stops
    trying for a short while, so a down Redis does not add a timeout to every message. Identity, one-time codes, the
    privacy vault and spend caps must use the strict store instead: losing those silently would be wrong."""

    def __init__(self, inner: KeyValueStore, breaker=None):
        from mpd_assistant.core.resilience import CircuitBreaker

        self._inner = inner
        self._breaker = breaker or CircuitBreaker(failure_threshold=3, reset_seconds=20.0)

    def _try(self, fn, fallback):
        from mpd_assistant.observability.metrics import DEGRADED

        if self._breaker.is_open:
            return fallback
        try:
            result = fn()
        except Exception:
            self._breaker.record_failure()
            DEGRADED.labels("redis_best_effort").inc()
            return fallback
        self._breaker.record_success()
        return result

    def get(self, key: str) -> Optional[Any]:
        return self._try(lambda: self._inner.get(key), None)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._try(lambda: self._inner.set(key, value, ttl_seconds), None)

    def delete(self, key: str) -> None:
        self._try(lambda: self._inner.delete(key), None)

    def incr(self, key: str, ttl_seconds: int) -> int:
        return self._try(lambda: self._inner.incr(key, ttl_seconds), 1)


class RedisKV:
    """Sync Redis adapter. Failures raise: identity, vault and spend-cap state must not silently vanish."""

    def __init__(self, client, prefix: str = "mpd:"):
        self._r = client
        self._prefix = prefix

    def get(self, key: str) -> Optional[Any]:
        raw = self._r.get(self._prefix + key)
        if raw is None:
            return None
        return json.loads(raw.decode() if isinstance(raw, bytes) else raw)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._r.set(self._prefix + key, json.dumps(value), ex=ttl_seconds)

    def delete(self, key: str) -> None:
        self._r.delete(self._prefix + key)

    def incr(self, key: str, ttl_seconds: int) -> int:
        full = self._prefix + key
        count = int(self._r.incr(full))
        if count == 1:
            self._r.expire(full, ttl_seconds)
        return count
