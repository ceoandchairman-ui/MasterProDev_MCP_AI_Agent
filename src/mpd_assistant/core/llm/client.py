"""LLM access behind one interface, with tiered models and ordered fallback."""

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
    pass


class LLM(Protocol):
    async def complete(self, messages: List[Message], *, tier: str = "mid", max_tokens: int = 512, temperature: float = 0.2) -> LLMResult: ...


class OpenAICompatibleLLM:
    """Works with any OpenAI-compatible chat endpoint (HuggingFace router, vLLM, Ollama, ...)."""

    def __init__(self, base_url: str, api_key: str, models: Dict[str, str], timeout: float = 30.0, client: httpx.AsyncClient | None = None):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._models = models
        self._timeout = timeout
        self._client = client

    async def complete(self, messages: List[Message], *, tier: str = "mid", max_tokens: int = 512, temperature: float = 0.2) -> LLMResult:
        model = self._models.get(tier) or self._models.get("mid")
        if not model:
            raise LLMError(f"No model configured for tier {tier}")
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if self._client:
                resp = await self._client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage") or {}
            return LLMResult(
                text=data["choices"][0]["message"]["content"] or "",
                tokens_in=int(usage.get("prompt_tokens", 0)),
                tokens_out=int(usage.get("completion_tokens", 0)),
                model=model,
            )
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"LLM call failed: {type(exc).__name__}") from exc  # never include the key or body


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
