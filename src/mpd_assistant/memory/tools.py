"""Memory as agent tools: memory_search and memory_save, with guardrails.

The user comes from the tool context, never from model-written arguments, so an agent cannot read or write another
person's memory. Saves go through the same validation as automatic extraction (consent, personal data, instruction-like
text). If the model has read untrusted content this turn (email, uploads, retrieved text), saving is refused outright.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Dict, Optional

from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.integrations.context import current_user, untrusted_in_context
from mpd_assistant.memory.long_term.store import KINDS, Candidate, MemoryStore
from mpd_assistant.retrieval.embeddings import Embedder
from mpd_assistant.routing.router import detect_language

logger = logging.getLogger(__name__)

SEARCHES_PER_HOUR = 60
SAVES_PER_HOUR = 10
SEARCH_TOKEN_BUDGET = 300
MAX_QUERY_CHARS = 300

ToolBackend = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]


class MemoryTools:
    def __init__(self, store: MemoryStore, has_consent: Callable[[str], bool], kv: KeyValueStore, embedder: Optional[Embedder] = None):
        self._store, self._consent, self._kv, self._embedder = store, has_consent, kv, embedder

    def _gate(self, kind: str, per_hour: int) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
        user_id = current_user()
        if not user_id:
            return None, {"status": "denied", "reason": "no_user"}
        if not self._consent(user_id):
            return None, {"status": "denied", "reason": "no_memory_consent"}
        if self._kv.incr(f"memtool:{kind}:{user_id}", 3600) > per_hour:
            return None, {"status": "denied", "reason": "rate_limited"}
        return user_id, None

    async def search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        user_id, denied = self._gate("search", SEARCHES_PER_HOUR)
        if denied:
            return denied
        query = str(args.get("query", ""))[:MAX_QUERY_CHARS].strip()
        if not query:
            return {"status": "error", "reason": "empty_query"}
        vector = None
        if self._embedder is not None:
            try:
                vector = (await self._embedder.embed([query]))[0]
            except Exception:
                logger.warning("memory_search embedding failed; using word overlap")
        found = self._store.recall(user_id, query, SEARCH_TOKEN_BUDGET, query_vector=vector)
        return {"status": "ok", "memories": [{"id": m.id, "kind": m.kind, "text": m.text} for m in found]}

    async def save(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if untrusted_in_context():
            return {"status": "denied", "reason": "untrusted_content_in_context"}
        user_id, denied = self._gate("save", SAVES_PER_HOUR)
        if denied:
            return denied
        kind = args.get("kind", "fact")
        text = args.get("text")
        if kind not in KINDS or not isinstance(text, str):
            return {"status": "error", "reason": "invalid_arguments"}
        slot = args.get("slot") if isinstance(args.get("slot"), str) else None
        result = self._store.write(user_id, Candidate(kind, text.strip(), importance=0.6, confidence=0.8, slot=slot, language=detect_language(text)), consent=True)
        if result.status in ("stored", "superseded") and result.memory is not None and self._embedder is not None:
            try:
                self._store.set_embedding(user_id, result.memory.id, (await self._embedder.embed([result.memory.text]))[0])
            except Exception:
                logger.warning("memory_save embedding failed; saved without a search vector")
        return {"status": result.status, "reason": result.reason}


def with_memory_tools(tools: MemoryTools, remote: ToolBackend) -> ToolBackend:
    """Route memory_* calls to the local store and everything else to the remote tool servers."""

    async def call(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool == "memory_search":
            return await tools.search(args)
        if tool == "memory_save":
            return await tools.save(args)
        return await remote(tool, args)

    return call


__all__ = ["MemoryTools", "with_memory_tools"]
