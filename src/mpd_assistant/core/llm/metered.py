"""Counts tokens per agent so cost can be attributed on the dashboards."""

from mpd_assistant.core.llm.client import LLM, LLMResult
from mpd_assistant.observability.metrics import TOKENS


class MeteredLLM:
    def __init__(self, inner: LLM, agent: str):
        self._inner, self._agent = inner, agent

    async def complete(self, messages, **kwargs) -> LLMResult:
        result = await self._inner.complete(messages, **kwargs)
        TOKENS.labels(self._agent, "in").inc(result.tokens_in)
        TOKENS.labels(self._agent, "out").inc(result.tokens_out)
        return result
