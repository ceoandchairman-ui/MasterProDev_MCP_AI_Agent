"""Circuit breaker around a model provider. After repeated failures it fails fast for a short while instead of making
every turn wait out a timeout; agents already turn LLMError into a polite templated reply."""

from typing import Optional

from mpd_assistant.core.llm.client import LLM, LLMError, LLMResult
from mpd_assistant.core.resilience import CircuitBreaker, CircuitOpen
from mpd_assistant.observability.metrics import DEGRADED


class BreakerLLM:
    def __init__(self, inner: LLM, breaker: Optional[CircuitBreaker] = None):
        self._inner = inner
        self._breaker = breaker or CircuitBreaker(failure_threshold=5, reset_seconds=30.0)

    async def complete(self, messages, **kwargs) -> LLMResult:
        try:
            self._breaker.allow()
        except CircuitOpen:
            DEGRADED.labels("model_provider").inc()
            raise LLMError("model provider temporarily unavailable") from None
        try:
            result = await self._inner.complete(messages, **kwargs)
        except LLMError:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()
        return result


__all__ = ["BreakerLLM"]
