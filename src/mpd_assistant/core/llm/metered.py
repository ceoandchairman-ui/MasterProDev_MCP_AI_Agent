"""Counts tokens per agent for cost attribution and enforces the daily token budget."""

from typing import Optional

from mpd_assistant.core.llm.budget import TokenBudget, current_scope
from mpd_assistant.core.llm.client import LLM, LLMResult
from mpd_assistant.observability.metrics import TOKENS


class MeteredLLM:
    def __init__(self, inner: LLM, agent: str, budget: Optional[TokenBudget] = None):
        self._inner, self._agent, self._budget = inner, agent, budget

    async def complete(self, messages, **kwargs) -> LLMResult:
        scope = current_scope()
        if self._budget is not None:
            self._budget.check(scope)
        result = await self._inner.complete(messages, **kwargs)
        TOKENS.labels(self._agent, "in").inc(result.tokens_in)
        TOKENS.labels(self._agent, "out").inc(result.tokens_out)
        if self._budget is not None:
            self._budget.record(scope, result.tokens_in + result.tokens_out)
        return result
