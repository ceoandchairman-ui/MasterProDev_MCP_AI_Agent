"""Episodic memory: one short note per past conversation, with its outcome, so a returning user is not a stranger.

Built from the rolling thread summary (already pseudonymized). Privacy tokens are replaced with plain words first,
because a token like <EMAIL_1> stops resolving once the session vault expires. The note then goes through the normal
memory validation, so consent, personal-data and instruction checks all apply. Retrieval and decay are the ordinary
ones: episodes fade faster than facts (45-day half-life).
"""

import hashlib
import re
from collections.abc import Callable
from typing import Optional

from mpd_assistant.agents.common import parse_json_object
from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.core.llm.client import LLM, LLMError
from mpd_assistant.memory.long_term.store import MAX_TEXT, Candidate, MemoryStore, WriteResult
from mpd_assistant.routing.router import detect_language

OUTCOMES = {"booked_call", "quote_sent", "paid", "escalated", "question_answered", "no_outcome"}
RECORDED_TTL = 90 * 24 * 3600
MIN_SUMMARY_CHARS = 40

_TOKEN = re.compile(r"<([A-Z_]+)_\d+>")
_TOKEN_WORDS = {"EMAIL": "their email", "PHONE": "their phone number", "PERSON": "the user", "NAME": "the user", "USER_EMAIL": "their email"}

CONDENSE_SYSTEM = (
    "Condense this conversation summary into ONE sentence of at most 220 characters, written about 'the user' in the "
    "past tense. Keep only what would matter in a later conversation. No names, contact details or placeholders. "
    'Output ONLY JSON: {"text": str}.'
)


def scrub_tokens(text: str) -> str:
    return _TOKEN.sub(lambda m: _TOKEN_WORDS.get(m.group(1), "something private"), text or "")


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[: end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0]).rstrip(" ,;") + ("." if end > limit // 2 else "...")


class EpisodeWriter:
    def __init__(self, store: MemoryStore, summaries, has_consent: Callable[[str], bool], kv: KeyValueStore, llm: Optional[LLM] = None):
        self._store, self._summaries, self._consent, self._kv, self._llm = store, summaries, has_consent, kv, llm

    async def _condense(self, summary: str) -> str:
        if self._llm is not None and len(summary) > MAX_TEXT - 40:
            try:
                result = await self._llm.complete(
                    [{"role": "system", "content": CONDENSE_SYSTEM}, {"role": "user", "content": summary}],
                    tier="cheap",
                    max_tokens=120,
                    temperature=0.0,
                )
                text = (parse_json_object(result.text) or {}).get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
            except LLMError:
                pass
        return summary

    async def record(self, user_id: str, thread_id: str, outcome: str = "no_outcome") -> Optional[WriteResult]:
        """Writes the episode once per distinct summary. Returns None when there is nothing to record or consent is off."""
        if not user_id or not self._consent(user_id):
            return None
        summary = scrub_tokens(self._summaries.context_for(thread_id)).strip()
        if len(summary) < MIN_SUMMARY_CHARS:
            return None
        digest = hashlib.sha256(f"{summary}|{outcome}".encode()).hexdigest()[:16]
        if self._kv.get(f"episode:{thread_id}") == digest:
            return None
        outcome = outcome if outcome in OUTCOMES else "no_outcome"
        suffix = "" if outcome == "no_outcome" else f" Outcome: {outcome.replace('_', ' ')}."
        body = _shorten(await self._condense(summary), MAX_TEXT - len(suffix) - 1)
        text = f"{body}{suffix}"
        result = self._store.write(user_id, Candidate("episode", text, importance=0.4 if outcome == "no_outcome" else 0.6, confidence=0.7, language=detect_language(text)), consent=True)
        if result.status in ("stored", "superseded", "duplicate"):
            self._kv.set(f"episode:{thread_id}", digest, RECORDED_TTL)
        return result


__all__ = ["EpisodeWriter", "OUTCOMES", "scrub_tokens"]
