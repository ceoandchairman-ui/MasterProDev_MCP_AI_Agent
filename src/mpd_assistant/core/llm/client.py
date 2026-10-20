"""LLM access behind one interface, with tiered models and ordered fallback."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Dict, List, Protocol

import httpx

Message = Dict[str, str]

TIERS = ("cheap", "mid", "reasoning")


@dataclass
class LLMResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


class LLMError(RuntimeError):
    """`status` is the provider's HTTP status when there was one (the body is never kept); `retryable` says a later
    attempt might work (rate limit, provider error, timeout) as opposed to a request that will always be refused."""

    def __init__(self, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status, self.retryable = status, retryable


RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class LLM(Protocol):
    async def complete(self, messages: List[Message], *, tier: str = "mid", max_tokens: int = 512, temperature: float = 0.2) -> LLMResult: ...


class OpenAICompatibleLLM:
    """Works with any OpenAI-compatible chat endpoint (HuggingFace router, vLLM, Ollama, ...).

    Transient trouble (429, 5xx, timeouts, dropped connections) is retried a couple of times with exponential backoff and
    jitter, honouring Retry-After. Permanent refusals (401, 402, 403, 400 ...) fail at once. At most `max_concurrency`
    requests are in flight at a time, so a burst queues instead of tripping the provider's rate limit."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        models: Dict[str, str],
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        retries: int = 2,
        base_delay: float = 0.5,
        max_wait: float = 8.0,
        max_concurrency: int = 8,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._models = models
        self._timeout = timeout
        self._client = client
        self._retries, self._base_delay, self._max_wait = max(0, retries), base_delay, max_wait
        self._slots = asyncio.Semaphore(max(1, max_concurrency))
        self._sleep, self._jitter = sleep, jitter

    async def _post(self, payload: dict, headers: dict) -> httpx.Response:
        async with self._slots:
            if self._client:
                return await self._client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            async with httpx.AsyncClient() as client:
                return await client.post(self._url, json=payload, headers=headers, timeout=self._timeout)

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        try:
            return max(0.0, float(resp.headers.get("retry-after", "")))
        except ValueError:
            return None

    def _pause(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self._max_wait)
        return min(self._max_wait, self._base_delay * (2**attempt)) * (0.5 + self._jitter() / 2)

    async def complete(self, messages: List[Message], *, tier: str = "mid", max_tokens: int = 512, temperature: float = 0.2) -> LLMResult:
        model = self._models.get(tier) or self._models.get("mid")
        if not model:
            raise LLMError(f"No model configured for tier {tier}")
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        headers = {"Authorization": f"Bearer {self._key}"}
        last: LLMError | None = None
        for attempt in range(self._retries + 1):
            retry_after = None
            try:
                resp = await self._post(payload, headers)
            except httpx.HTTPError as exc:  # timeouts, refused or dropped connections
                last = LLMError(f"LLM call failed: {type(exc).__name__}", retryable=True)  # never include the key or body
            else:
                if resp.status_code == 200:
                    return self._parse(resp, model)
                retryable = resp.status_code in RETRYABLE_STATUS
                last = LLMError(f"LLM call failed: HTTP {resp.status_code}", status=resp.status_code, retryable=retryable)
                if not retryable:
                    raise last
                retry_after = self._retry_after(resp)
            if attempt < self._retries:
                from mpd_assistant.observability.metrics import LLM_RETRIES

                LLM_RETRIES.labels(model, str(last.status or "network")).inc()
                await self._sleep(self._pause(attempt, retry_after))
        raise last  # type: ignore[misc]

    @staticmethod
    def _parse(resp: httpx.Response, model: str) -> LLMResult:
        try:
            data = resp.json()
            usage = data.get("usage") or {}
            return LLMResult(
                text=data["choices"][0]["message"]["content"] or "",
                tokens_in=int(usage.get("prompt_tokens", 0)),
                tokens_out=int(usage.get("completion_tokens", 0)),
                model=model,
            )
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
            raise LLMError(f"LLM call failed: {type(exc).__name__}") from exc


class FallbackLLM:
    """Try providers in order; the first success wins. Partial output from a failed provider is never reused."""

    def __init__(self, providers: List[LLM]):
        if not providers:
            raise ValueError("At least one provider is required")
        self._providers = providers

    async def complete(self, messages: List[Message], *, tier: str = "mid", max_tokens: int = 512, temperature: float = 0.2) -> LLMResult:
        last: Exception | None = None
        for provider in self._providers:
            try:
                return await provider.complete(messages, tier=tier, max_tokens=max_tokens, temperature=temperature)
            except LLMError as exc:
                last = exc
        raise LLMError("All LLM providers failed") from last


class FakeLLM:
    """Deterministic test double: returns queued replies, records prompts."""

    def __init__(self, replies: List[str]):
        self.replies = list(replies)
        self.calls: List[List[Message]] = []

    async def complete(self, messages: List[Message], *, tier: str = "mid", max_tokens: int = 512, temperature: float = 0.2) -> LLMResult:
        self.calls.append(messages)
        if not self.replies:
            raise LLMError("no more fake replies")
        text = self.replies.pop(0)
        return LLMResult(text, tokens_in=sum(len(m["content"]) // 4 for m in messages), tokens_out=len(text) // 4, model="fake")
