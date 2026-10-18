"""Long-term memory: validated writes, supersede-don't-overwrite, scored and budgeted recall.

The LLM may *propose* memories; this module decides what is stored.
"""

import math
import re
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Protocol

from mpd_assistant.memory.short_term.window import estimate_tokens
from mpd_assistant.privacy.detector import detect

KINDS = {"fact", "preference", "episode", "procedure"}
MAX_TEXT = 300
MIN_CONFIDENCE = 0.5
CONFIRM_BELOW = 0.75
HALF_LIFE_DAYS = {"fact": 365.0, "preference": 180.0, "episode": 45.0, "procedure": 365.0}
FORGET_BELOW = 0.05
_DAY = 86400.0


@dataclass
class Candidate:
    kind: str
    text: str
    importance: float = 0.5
    confidence: float = 0.8
    slot: Optional[str] = None  # e.g. "preferred_language"; same slot + different text = contradiction
    source: str = "user_message"  # user_message | tool_result | upload | email


@dataclass
class Memory:
    id: str
    user_id: str
    kind: str
    text: str
    importance: float
    confidence: float
    slot: Optional[str]
    created_at: float
    valid_to: Optional[float] = None
    last_used: Optional[float] = None
    uses: int = 0
    superseded_by: Optional[str] = None


@dataclass
class WriteResult:
    status: str  # stored | duplicate | superseded | rejected | needs_confirmation
    reason: str = ""
    memory: Optional[Memory] = None


_TOKEN_RE = re.compile(r"<[A-Z_]+_\d+>")
UNTRUSTED_SOURCES = {"tool_result", "upload", "email"}


def validate(candidate: Candidate, consent: bool) -> Optional[str]:
    """Return a rejection reason, or None if the candidate may be considered for storage."""
    if not consent:
        return "no_memory_consent"
    if candidate.source in UNTRUSTED_SOURCES:
        return "untrusted_source"
    if candidate.kind not in KINDS:
        return "invalid_kind"
    text = candidate.text.strip()
    if not text or len(text) > MAX_TEXT:
        return "invalid_length"
    if candidate.confidence < MIN_CONFIDENCE:
        return "low_confidence"
    if _TOKEN_RE.search(text):
        return "contains_privacy_token"  # tokens stop resolving when the session vault expires
    if detect(text):
        return "contains_personal_or_secret_data"  # contact details live in the user record, not in memory
    if re.search(r"(?i)\b(ignore (all|previous)|system prompt|you must always)\b", text):
        return "instruction_like_text"
    return None


def _tokens(text: str) -> set:
    return set(re.findall(r"\w+", text.lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


class Similarity(Protocol):
    def __call__(self, query: str, text: str) -> float: ...


class MemoryRepository(Protocol):
    def load_user(self, user_id: str) -> List[Memory]: ...
    def save(self, memory: Memory) -> None: ...
    def delete_user(self, user_id: str) -> int: ...


class InMemoryRepository:
    def __init__(self):
        self._items: Dict[str, Memory] = {}

    def load_user(self, user_id: str) -> List[Memory]:
        return [m for m in self._items.values() if m.user_id == user_id]

    def save(self, memory: Memory) -> None:
        self._items[memory.id] = memory

    def delete_user(self, user_id: str) -> int:
        ids = [i for i, m in self._items.items() if m.user_id == user_id]
        for i in ids:
            del self._items[i]
        return len(ids)


class MemoryStore:
    def __init__(self, clock: Callable[[], float] = time.time, similarity: Similarity = jaccard, repo: Optional[MemoryRepository] = None):
        self._repo: MemoryRepository = repo or InMemoryRepository()
        self._clock = clock
        self._similarity = similarity

    def _active(self, user_id: str) -> List[Memory]:
        return [m for m in self._repo.load_user(user_id) if m.valid_to is None]

    def write(self, user_id: str, candidate: Candidate, consent: bool, confirmed: bool = False) -> WriteResult:
        reason = validate(candidate, consent)
        if reason:
            return WriteResult("rejected", reason)

        now = self._clock()
        active = self._active(user_id)
        for existing in active:
            if existing.kind == candidate.kind and jaccard(existing.text, candidate.text) >= 0.8:
                existing.importance = max(existing.importance, candidate.importance)
                self._repo.save(existing)
                return WriteResult("duplicate", memory=existing)

        conflicting = [m for m in active if candidate.slot and m.slot == candidate.slot]
        if conflicting and candidate.confidence < CONFIRM_BELOW and not confirmed:
            return WriteResult("needs_confirmation", "conflicts_with_existing_memory", conflicting[0])

        memory = Memory(uuid.uuid4().hex, user_id, candidate.kind, candidate.text.strip(), candidate.importance, candidate.confidence, candidate.slot, now)
        self._repo.save(memory)
        for old in conflicting:
            old.valid_to, old.superseded_by = now, memory.id
            self._repo.save(old)
        return WriteResult("superseded" if conflicting else "stored", memory=memory)

    def _recency(self, memory: Memory, now: float) -> float:
        age_days = max(0.0, (now - (memory.last_used or memory.created_at)) / _DAY)
        return 0.5 ** (age_days / HALF_LIFE_DAYS[memory.kind])

    def recall(self, user_id: str, query: str, token_budget: int, limit: int = 5, diversity: float = 0.7) -> List[Memory]:
        """Rank by relevance x recency x importance, pick greedily with MMR diversity, stop at the token budget."""
        now = self._clock()
        scored = []
        for m in self._active(user_id):
            relevance = self._similarity(query, m.text)
            if relevance <= 0:
                continue
            scored.append((relevance * self._recency(m, now) * (0.5 + m.importance), m))
        scored.sort(key=lambda p: p[0], reverse=True)

        chosen: List[Memory] = []
        used = 0
        pool = scored[:]
        while pool and len(chosen) < limit:
            def mmr(pair):
                score, m = pair
                redundancy = max((jaccard(m.text, c.text) for c in chosen), default=0.0)
                return diversity * score - (1 - diversity) * redundancy

            best = max(pool, key=mmr)
            pool.remove(best)
            cost = estimate_tokens(best[1].text)
            if used + cost > token_budget:
                continue
            chosen.append(best[1])
            used += cost
        for m in chosen:
            m.last_used, m.uses = now, m.uses + 1
            self._repo.save(m)
        return chosen

    def decay_and_forget(self, user_id: str) -> int:
        """Archive memories whose retention score has decayed away. Returns how many were forgotten."""
        now = self._clock()
        forgotten = 0
        for m in self._active(user_id):
            reinforcement = 1 + math.log1p(m.uses)
            if self._recency(m, now) * (0.5 + m.importance) * reinforcement < FORGET_BELOW:
                m.valid_to = now
                self._repo.save(m)
                forgotten += 1
        return forgotten

    def export(self, user_id: str) -> List[dict]:
        return [m.__dict__.copy() for m in self._repo.load_user(user_id)]

    def delete_all(self, user_id: str) -> int:
        return self._repo.delete_user(user_id)


__all__ = ["Candidate", "Memory", "MemoryStore", "WriteResult", "validate"]
