"""Response cache with TTL, single-flight (no stampede) and metrics. Backends are pluggable (memory, Redis)."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Dict, Protocol, Tuple

from mpd_assistant.observability.metrics import CACHE_EVENTS

DEFAULT_TTL_SECONDS = {"faq": 24 * 3600, "knowledge_question": 3600, "greeting": 24 * 3600}


class CacheBackend(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...
    async def delete_prefix(self, prefix: str) -> int: ...


class MemoryBackend:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._data: Dict[str, Tuple[str, float]] = {}
        self._clock = clock

    async def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        if item[1] < self._clock():
            del self._data[key]
            return None
        return item[0]

    async def set(self, key: str, value: str, ttl: int) -> None:
        self._data[key] = (value, self._clock() + ttl)

    async def delete_prefix(self, prefix: str) -> int:
        keys = [k for k in self._data if k.startswith(prefix)]
        for k in keys:
            del self._data[k]
        return len(keys)


class RedisBackend:
    """Thin adapter over redis.asyncio.Redis; any Redis failure degrades to a cache miss."""

    def __init__(self, client):
        self._r = client

    async def get(self, key: str) -> str | None:
        try:
            value = await self._r.get(key)
            return value.decode() if isinstance(value, bytes) else value
        except Exception:
            return None

    async def set(self, key: str, value: str, ttl: int) -> None:
        try:
            await self._r.set(key, value, ex=ttl)
        except Exception:
            return None

    async def delete_prefix(self, prefix: str) -> int:
        try:
            count = 0
            async for key in self._r.scan_iter(match=f"{prefix}*", count=200):
                count += await self._r.delete(key)
            return count
        except Exception:
            return 0


class ResponseCache:
    def __init__(self, backend: CacheBackend, layer: str = "response"):
        self._backend = backend
        self._layer = layer
        self._inflight: Dict[str, asyncio.Future] = {}

    @property
    def backend(self) -> CacheBackend:
        return self._backend

    async def get(self, key: str) -> str | None:
        value = await self._backend.get(key)
        CACHE_EVENTS.labels(self._layer, "hit" if value is not None else "miss").inc()
        return value

    async def set(self, key: str, value: str, ttl: int) -> None:
        await self._backend.set(key, value, ttl)

    async def get_or_compute(self, key: str, compute: Callable[[], Awaitable[Tuple[str, bool]]], ttl: int) -> str:
        """compute() returns (value, cacheable). Concurrent callers for one key share a single computation."""
        cached = await self.get(key)
        if cached is not None:
            return cached
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value, cacheable = await compute()
            if cacheable:
                await self.set(key, value, ttl)
            future.set_result(value)
            return value
        except Exception as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved so unused futures do not warn
            raise
        finally:
            self._inflight.pop(key, None)

    async def invalidate(self, prefix: str = "resp:") -> int:
        """Called on corpus or prompt version bumps."""
        return await self._backend.delete_prefix(prefix)
