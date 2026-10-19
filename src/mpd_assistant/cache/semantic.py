"""Semantic cache: reuse an answer when a new question is nearly identical in meaning to an earlier one.

Only shareable, non-personalized knowledge answers are eligible. Answers live in the shared cache backend (so TTL
and purges apply); the vector index is per process and rebuilds as traffic arrives, so a cold replica is a miss, not
an error.
"""

import math
import uuid
from collections import OrderedDict
from typing import List, Optional, Tuple

from mpd_assistant.cache.store import CacheBackend
from mpd_assistant.observability.metrics import CACHE_EVENTS
from mpd_assistant.retrieval.embeddings import Embedder, EmbeddingError

DEFAULT_THRESHOLD = 0.92
MAX_PER_SCOPE = 300
MAX_SCOPES = 50


def cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SemanticCache:
    def __init__(self, backend: CacheBackend, embedder: Embedder, threshold: float = DEFAULT_THRESHOLD):
        self._backend, self._embedder, self._threshold = backend, embedder, threshold
        self._index: "OrderedDict[str, List[Tuple[str, List[float]]]]" = OrderedDict()

    @staticmethod
    def scope(tenant: str, locale: str, agent: str, prompt_version: str, corpus_version: str) -> str:
        """Answers are only comparable inside one tenant, language, agent, prompt version and corpus version."""
        return f"{tenant}:{locale}:{agent}:{prompt_version}:{corpus_version}"

    def _entries(self, scope: str) -> List[Tuple[str, List[float]]]:
        entries = self._index.get(scope)
        if entries is None:
            entries = self._index[scope] = []
            while len(self._index) > MAX_SCOPES:
                self._index.popitem(last=False)
        else:
            self._index.move_to_end(scope)
        return entries

    async def lookup(self, scope: str, text: str) -> Optional[str]:
        entries = self._index.get(scope)
        if not entries:
            CACHE_EVENTS.labels("semantic", "miss").inc()
            return None
        try:
            vector = (await self._embedder.embed([text]))[0]
        except EmbeddingError:
            return None  # a cache must never be the reason a question fails
        best_id, best = None, 0.0
        for entry_id, candidate in entries:
            score = cosine(vector, candidate)
            if score > best:
                best_id, best = entry_id, score
        if best_id is not None and best >= self._threshold:
            answer = await self._backend.get(f"sem:{scope}:{best_id}")
            if answer is not None:
                CACHE_EVENTS.labels("semantic", "hit").inc()
                return answer
            entries[:] = [e for e in entries if e[0] != best_id]  # the answer expired or was purged
        CACHE_EVENTS.labels("semantic", "miss").inc()
        return None

    async def store(self, scope: str, text: str, answer: str, ttl: int) -> None:
        try:
            vector = (await self._embedder.embed([text]))[0]
        except EmbeddingError:
            return
        entries = self._entries(scope)
        entry_id = uuid.uuid4().hex[:16]
        await self._backend.set(f"sem:{scope}:{entry_id}", answer, ttl)
        entries.append((entry_id, vector))
        if len(entries) > MAX_PER_SCOPE:
            del entries[: len(entries) - MAX_PER_SCOPE]

    async def invalidate(self) -> int:
        """Corpus or prompt version bump: drop the index and the stored answers."""
        self._index.clear()
        return await self._backend.delete_prefix("sem:")


__all__ = ["SemanticCache", "cosine"]
