"""Counts tokens per agent for cost attribution, enforces the daily token budget, and watches prompt-prefix stability.

Providers cache the start of a prompt. That only helps when the leading system prompt is identical call after call, so
each call's system prompt is fingerprinted and compared with the agent's recent ones. Language or catalog changes
legitimately produce a few distinct prefixes; a prefix that is new on every call means something per-request (a
timestamp, an id) leaked into the system prompt.
"""

import hashlib
from collections import deque
from typing import Deque, Optional

from mpd_assistant.core.llm.budget import TokenBudget, current_scope
from mpd_assistant.core.llm.client import LLM, LLMResult
from mpd_assistant.observability.metrics import PROMPT_PREFIX, TOKENS

RECENT_PREFIXES = 8


def prefix_fingerprint(messages) -> str:
    """Hash of the leading run of system messages: the part a provider can cache."""
    lead = []
    for message in messages:
        if message.get("role") != "system":
            break
        lead.append(str(message.get("content", "")))
    return hashlib.sha256("\n".join(lead).encode()).hexdigest()[:16]


class MeteredLLM:
    def __init__(self, inner: LLM, agent: str, budget: Optional[TokenBudget] = None):
        self._inner, self._agent, self._budget = inner, agent, budget
        self._recent: Deque[str] = deque(maxlen=RECENT_PREFIXES)

    def _track_prefix(self, messages) -> None:
        fingerprint = prefix_fingerprint(messages)
        PROMPT_PREFIX.labels(self._agent, "reused" if fingerprint in self._recent else "new").inc()
        if fingerprint not in self._recent:
            self._recent.append(fingerprint)

    async def complete(self, messages, **kwargs) -> LLMResult:
        scope = current_scope()
        if self._budget is not None:
            self._budget.check(scope)
        self._track_prefix(messages)
        result = await self._inner.complete(messages, **kwargs)
        TOKENS.labels(self._agent, "in").inc(result.tokens_in)
        TOKENS.labels(self._agent, "out").inc(result.tokens_out)
        if self._budget is not None:
            self._budget.record(scope, result.tokens_in + result.tokens_out)
        return result


__all__ = ["MeteredLLM", "prefix_fingerprint"]
