"""Procedural memory: a reviewed library of reply patterns used as few-shot examples.

Anything may be *proposed* (for example a well-rated reply), but nothing reaches a model until a person approves it.
Proposals are screened for personal data, privacy tokens and instruction-like text, and the backlog is capped so a
bad day cannot flood the review queue.
"""

import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Dict, List, Protocol

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.models import ResponsePattern
from mpd_assistant.memory.long_term.store import jaccard
from mpd_assistant.privacy.detector import detect

MAX_TEXT = 600
MIN_TEXT = 8
MAX_PROPOSED_BACKLOG = 200
DUPLICATE_SIMILARITY = 0.85
PROPOSED, APPROVED, REJECTED = "proposed", "approved", "rejected"

_TOKEN = re.compile(r"<[A-Z_]+_\d+>")
_INSTRUCTION = re.compile(r"(?i)\b(ignore (all|previous)|system prompt|you must always|you are now)\b")


@dataclass
class Pattern:
    id: str
    intent: str
    language: str
    user_text: str
    reply_text: str
    status: str = PROPOSED
    reviewed_by: str | None = None
    created_at: float = field(default_factory=time.time)


class PatternRepository(Protocol):
    def save(self, pattern: Pattern) -> None: ...
    def get(self, pattern_id: str) -> Pattern | None: ...
    def list(self, status: str | None = None, intent: str | None = None, language: str | None = None, limit: int = 50) -> List[Pattern]: ...


class MemoryPatternRepository:
    def __init__(self):
        self._items: Dict[str, Pattern] = {}

    def save(self, pattern: Pattern) -> None:
        self._items[pattern.id] = pattern

    def get(self, pattern_id: str) -> Pattern | None:
        return self._items.get(pattern_id)

    def list(self, status=None, intent=None, language=None, limit=50) -> List[Pattern]:
        rows = [p for p in self._items.values() if (status is None or p.status == status) and (intent is None or p.intent == intent) and (language is None or p.language == language)]
        return sorted(rows, key=lambda p: p.created_at)[:limit]


class SqlPatternRepository:
    def __init__(self, engine: Engine, tenant_id: str):
        self._engine, self._tenant = engine, tenant_id

    @staticmethod
    def _domain(row: ResponsePattern) -> Pattern:
        created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
        return Pattern(row.id, row.intent, row.language, row.user_text, row.reply_text, row.status, row.reviewed_by, created.timestamp())

    def save(self, pattern: Pattern) -> None:
        with DbSession(self._engine) as db:
            row = db.get(ResponsePattern, pattern.id) or ResponsePattern(id=pattern.id, tenant_id=self._tenant, created_at=datetime.fromtimestamp(pattern.created_at, UTC))
            row.intent, row.language = pattern.intent, pattern.language
            row.user_text, row.reply_text = pattern.user_text, pattern.reply_text
            row.status, row.reviewed_by = pattern.status, pattern.reviewed_by
            row.reviewed_at = datetime.now(UTC) if pattern.status != PROPOSED else None
            db.add(row)
            db.commit()

    def get(self, pattern_id: str) -> Pattern | None:
        with DbSession(self._engine) as db:
            row = db.get(ResponsePattern, pattern_id)
            return self._domain(row) if row and row.tenant_id == self._tenant else None

    def list(self, status=None, intent=None, language=None, limit=50) -> List[Pattern]:
        with DbSession(self._engine) as db:
            query = select(ResponsePattern).where(ResponsePattern.tenant_id == self._tenant)
            if status:
                query = query.where(ResponsePattern.status == status)
            if intent:
                query = query.where(ResponsePattern.intent == intent)
            if language:
                query = query.where(ResponsePattern.language == language)
            return [self._domain(r) for r in db.scalars(query.order_by(ResponsePattern.created_at).limit(limit))]


def screen(text: str) -> str | None:
    """Reason the text may not enter the library, or None."""
    text = (text or "").strip()
    if not (MIN_TEXT <= len(text) <= MAX_TEXT):
        return "invalid_length"
    if _TOKEN.search(text):
        return "contains_privacy_token"
    if detect(text):
        return "contains_personal_or_secret_data"
    if _INSTRUCTION.search(text):
        return "instruction_like_text"
    return None


class PatternLibrary:
    def __init__(self, repo: PatternRepository | None = None):
        self._repo: PatternRepository = repo or MemoryPatternRepository()

    def propose(self, intent: str, language: str, user_text: str, reply_text: str) -> Pattern | None:
        """Returns the new proposal, or None when it was screened out, a duplicate, or the review backlog is full."""
        if screen(user_text) or screen(reply_text):
            return None
        existing = self._repo.list(intent=intent, language=language, limit=500)
        if any(p.status != REJECTED and jaccard(p.reply_text, reply_text) >= DUPLICATE_SIMILARITY for p in existing):
            return None
        if len(self._repo.list(status=PROPOSED, limit=MAX_PROPOSED_BACKLOG + 1)) > MAX_PROPOSED_BACKLOG:
            return None
        pattern = Pattern(uuid.uuid4().hex, intent, language, user_text.strip(), reply_text.strip())
        self._repo.save(pattern)
        return pattern

    def pending(self, limit: int = 50) -> List[Pattern]:
        return self._repo.list(status=PROPOSED, limit=limit)

    def _review(self, pattern_id: str, reviewer: str, status: str) -> bool:
        pattern = self._repo.get(pattern_id)
        if pattern is None or pattern.status != PROPOSED or not reviewer.strip():
            return False
        pattern.status, pattern.reviewed_by = status, reviewer.strip()[:64]
        self._repo.save(pattern)
        return True

    def approve(self, pattern_id: str, reviewer: str) -> bool:
        return self._review(pattern_id, reviewer, APPROVED)

    def reject(self, pattern_id: str, reviewer: str) -> bool:
        return self._review(pattern_id, reviewer, REJECTED)

    def examples_for(self, intent: str, language: str, limit: int = 2) -> List[Pattern]:
        """Approved patterns only, newest approvals last so the freshest style is closest to the question."""
        approved = self._repo.list(status=APPROVED, intent=intent, language=language, limit=limit)
        return approved or ([] if language == "en" else self._repo.list(status=APPROVED, intent=intent, language="en", limit=limit))

    def few_shot_block(self, intent: str, language: str, limit: int = 2) -> str:
        examples = self.examples_for(intent, language, limit)
        if not examples:
            return ""
        shots = "\n\n".join(f"User: {p.user_text}\nAssistant: {p.reply_text}" for p in examples)
        return f"Approved examples of good replies (style guide only; do not copy facts from them):\n{shots}\n\n"


__all__ = ["Pattern", "PatternLibrary", "SqlPatternRepository", "MemoryPatternRepository", "screen"]
