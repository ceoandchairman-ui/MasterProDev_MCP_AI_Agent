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
