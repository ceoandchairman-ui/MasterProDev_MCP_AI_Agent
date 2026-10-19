"""Memory in the request path: recall before the turn, propose after it. The model proposes, code decides.

With an embedder, recall also matches by meaning (so a question in French finds a fact stored in English). Embedding
failures never break a turn: recall falls back to word overlap.
"""

import logging
from collections.abc import Callable
from typing import List

from mpd_assistant.agents.common import parse_json_object
from mpd_assistant.core.llm.client import LLM, LLMError
from mpd_assistant.memory.long_term.store import KINDS, Candidate, MemoryStore
from mpd_assistant.retrieval.embeddings import Embedder
from mpd_assistant.routing.router import detect_language

logger = logging.getLogger(__name__)

MIN_CHARS_TO_EXTRACT = 30
MAX_PROPOSALS = 3

PROPOSE_SYSTEM = (
    "From the user's message, extract at most 3 durable facts or preferences that would help in future "
    'conversations (their business, needs, tools, language, tone preferences). Output ONLY JSON: '
    '{"memories": [{"kind": "fact|preference|episode|procedure", "text": str, "importance": 0-1, "confidence": 0-1, "slot": str|null}]}. '
    "Never include contact details, names, secrets or placeholders like <EMAIL_1>. Output {\"memories\": []} if nothing is durable."
)


def _clamp(value, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


class MemoryWiring:
    def __init__(
        self,
        store: MemoryStore,
        llm: LLM | None,
        has_consent: Callable[[str], bool],
        token_budget: int = 150,
        embedder: Embedder | None = None,
    ):
        self._store, self._llm, self._consent, self._budget, self._embedder = store, llm, has_consent, token_budget, embedder

    def _allowed(self, user_id: str | None) -> bool:
        return bool(user_id) and self._consent(user_id)

    async def _embed(self, texts: List[str]):
        if self._embedder is None:
            return None
        try:
            return await self._embedder.embed(texts)
        except Exception:
            logger.warning("memory embedding failed; using word overlap only")
            return None

    async def before(self, user_id: str | None, safe_text: str) -> str:
        if not self._allowed(user_id):
            return ""
        vectors = await self._embed([safe_text])
        memories = self._store.recall(user_id, safe_text, self._budget, query_vector=vectors[0] if vectors else None)
        return "\n".join(f"- {m.text}" for m in memories)

    async def after(self, user_id: str | None, safe_text: str, *, allow: bool) -> int:
        """Returns how many memories were stored. Never raises: memory must not break a conversation."""
        if not allow or self._llm is None or not self._allowed(user_id) or len(safe_text) < MIN_CHARS_TO_EXTRACT:
            return 0
        try:
            stored = []
            for candidate in await self._propose(safe_text):
                result = self._store.write(user_id, candidate, consent=True)
                if result.status in ("stored", "superseded") and result.memory is not None:
                    stored.append(result.memory)
            if stored:
                vectors = await self._embed([m.text for m in stored])
                if vectors and len(vectors) == len(stored):
                    for memory, vector in zip(stored, vectors, strict=True):
                        self._store.set_embedding(user_id, memory.id, vector)
            return len(stored)
        except Exception:
            return 0

    async def _propose(self, safe_text: str) -> List[Candidate]:
        try:
            result = await self._llm.complete(
                [{"role": "system", "content": PROPOSE_SYSTEM}, {"role": "user", "content": safe_text}],
                tier="cheap",
                max_tokens=250,
                temperature=0.0,
            )
        except LLMError:
            return []
        raw = (parse_json_object(result.text) or {}).get("memories")
        candidates: List[Candidate] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or item.get("kind") not in KINDS or not isinstance(item.get("text"), str):
                continue
            slot = item.get("slot") if isinstance(item.get("slot"), str) else None
            text = item["text"].strip()
            candidates.append(
                Candidate(
                    kind=item["kind"],
                    text=text,
                    importance=_clamp(item.get("importance"), 0.5),
                    confidence=_clamp(item.get("confidence"), 0.7),
                    slot=slot,
                    language=detect_language(text),
                )
            )
        return candidates[:MAX_PROPOSALS]
