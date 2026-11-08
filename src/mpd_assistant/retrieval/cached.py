"""Short-lived cache in front of any retriever. Embedding plus rerank is the slow, paid part of a knowledge answer, and
the same question comes up again within minutes. The scope (normally the corpus version) is part of the key, so
re-indexing the documents makes every old entry miss. Questions containing personal data are never cached."""

import hashlib
import json
import re
from dataclasses import asdict
from typing import List, Protocol

from mpd_assistant.cache.keys import normalize_query
from mpd_assistant.cache.store import CacheBackend, ResponseCache
from mpd_assistant.privacy.detector import detect
from mpd_assistant.retrieval.hybrid import Hit

_TOKEN_RE = re.compile(r"<[A-Z_]+_\d+>")
DEFAULT_TTL_SECONDS = 300


class Retriever(Protocol):
    async def search(self, query: str) -> List[Hit]: ...


class CachedRetriever:
    def __init__(self, inner: Retriever, backend: CacheBackend, scope: str, ttl: int = DEFAULT_TTL_SECONDS):
        self._inner, self._cache, self._scope, self._ttl = inner, ResponseCache(backend, layer="retrieval"), scope, ttl

    async def search(self, query: str) -> List[Hit]:
        if _TOKEN_RE.search(query) or detect(query):
            return await self._inner.search(query)
        digest = hashlib.sha256(normalize_query(query).encode()).hexdigest()[:32]
        key = f"retr:{self._scope}:{digest}"
        cached = await self._cache.get(key)
        if cached is not None:
            return [Hit(**row) for row in json.loads(cached)]
        hits = await self._inner.search(query)
        await self._cache.set(key, json.dumps([asdict(h) for h in hits]), self._ttl)
        return hits

    async def invalidate(self) -> int:
        return await self._cache.invalidate("retr:")


__all__ = ["CachedRetriever"]
