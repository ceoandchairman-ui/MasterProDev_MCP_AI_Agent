"""Builds the model layer from settings: one chain per tier, each with its own endpoint, circuit breaker and fallback.

    cheap / mid / reasoning / compress  ->  [primary model -> optional fallback model], each behind its own circuit breaker

A separate breaker per tier and model means an outage of the reasoning model does not stop the cheap and mid tiers.
"""

from typing import Any, Callable, Dict, List

from mpd_assistant.core.llm.client import TIERS, FallbackLLM, LLMError, LLMResult, Message, OpenAICompatibleLLM
from mpd_assistant.core.llm.resilient import BreakerLLM

# Seconds a single call may take, per tier. The reasoning tier writes long structured output, so it gets longer.
TIER_TIMEOUTS = {"cheap": 20.0, "mid": 30.0, "reasoning": 40.0, "compress": 30.0}


class RoutedLLM:
    """Sends each call to the chain for its tier; an unknown tier uses the mid chain."""

    def __init__(self, routes: Dict[str, Any], default: str = "mid"):
        if default not in routes:
            raise ValueError(f"No route for the default tier {default}")
        self._routes, self._default = routes, default

    @property
    def tiers(self) -> List[str]:
        return sorted(self._routes)

    async def complete(self, messages: List[Message], *, tier: str = "mid", max_tokens: int = 512, temperature: float = 0.2) -> LLMResult:
        chain = self._routes.get(tier) or self._routes[self._default]
        return await chain.complete(messages, tier=tier, max_tokens=max_tokens, temperature=temperature)


def _tier_model(settings, tier: str) -> str | None:
    mid = settings.HUGGINGFACE_MODEL
    if tier == "mid":
        return mid
    if tier == "cheap":
        return settings.LLM_MODEL_CHEAP or mid
    if tier == "compress":  # its own model when set, else whatever the cheap tier uses
        return getattr(settings, "LLM_MODEL_COMPRESS", None) or settings.LLM_MODEL_CHEAP or mid
    return settings.LLM_MODEL_REASONING or mid


def build_llm(settings, client_cls: Callable[..., Any] = OpenAICompatibleLLM) -> RoutedLLM | None:
    """None when there is no mid-tier model or key (the agents then answer from templates)."""
    routes: Dict[str, Any] = {}
    for tier in TIERS:
        model = _tier_model(settings, tier)
        base = getattr(settings, f"LLM_{tier.upper()}_BASE_URL", None) or settings.LLM_BASE_URL
        key = getattr(settings, f"LLM_{tier.upper()}_API_KEY", None) or settings.HUGGINGFACE_API_KEY
        if not model or not key:
            continue

        def client(name: str, base=base, key=key, tier=tier):
            return client_cls(
                base, key, {t: name for t in TIERS},
                timeout=TIER_TIMEOUTS[tier], retries=settings.LLM_MAX_RETRIES, max_concurrency=settings.LLM_MAX_CONCURRENCY,
            )

        chain: Any = BreakerLLM(client(model))
        fallback = getattr(settings, f"LLM_FALLBACK_{tier.upper()}", None)
        if fallback and fallback != model:
            chain = FallbackLLM([chain, BreakerLLM(client(fallback))])
        routes[tier] = chain
    if "mid" not in routes:
        return None
    return RoutedLLM(routes, default="mid")


__all__ = ["RoutedLLM", "TIER_TIMEOUTS", "LLMError", "build_llm"]
