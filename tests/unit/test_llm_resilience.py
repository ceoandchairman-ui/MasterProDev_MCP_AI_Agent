"""The model layer: retries with backoff, Retry-After, a concurrency cap, per-tier breakers, routing and fallback."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from mpd_assistant.core.llm.client import FakeLLM, LLMError, LLMResult, OpenAICompatibleLLM
from mpd_assistant.core.llm.factory import RoutedLLM, build_llm
from mpd_assistant.core.llm.resilient import BreakerLLM, counts_against_provider
from mpd_assistant.core.resilience import CircuitBreaker
from mpd_assistant.observability.metrics import LLM_RETRIES

MSG = [{"role": "user", "content": "q"}]
OK = {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}


def llm(handler, **kw):
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleLLM("https://x/v1", "SECRETKEY", {"mid": "m"}, client=client, sleep=sleep, jitter=lambda: 1.0, **kw), waits


# --- retries --------------------------------------------------------------------------------
async def test_a_transient_failure_is_retried_with_growing_pauses():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=OK)

    model, waits = llm(handler)
    result = await model.complete(MSG)
    assert result.text == "hi" and len(calls) == 3 and waits == [0.5, 1.0]  # 0.5 * 2**attempt, jitter pinned to its maximum


async def test_rate_limits_honour_retry_after_but_never_wait_longer_than_the_cap():
    sequence = iter([httpx.Response(429, headers={"retry-after": "3"}), httpx.Response(429, headers={"retry-after": "120"}), httpx.Response(200, json=OK)])
    model, waits = llm(lambda request: next(sequence))
    assert (await model.complete(MSG)).text == "hi" and waits == [3.0, 8.0]


async def test_timeouts_and_dropped_connections_are_retried_then_reported():
    def handler(request):
        raise httpx.ConnectTimeout("slow")

    model, waits = llm(handler)
    with pytest.raises(LLMError) as exc:
        await model.complete(MSG)
    assert exc.value.retryable and exc.value.status is None and "ConnectTimeout" in str(exc.value) and len(waits) == 2


async def test_it_gives_up_after_the_last_retry_and_says_which_status():
    model, waits = llm(lambda request: httpx.Response(502, text="bad gateway SECRETKEY"), retries=1)
    with pytest.raises(LLMError) as exc:
        await model.complete(MSG)
    assert exc.value.status == 502 and exc.value.retryable and len(waits) == 1
    assert "HTTP 502" in str(exc.value) and "SECRETKEY" not in str(exc.value) and "bad gateway" not in str(exc.value)


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422])
async def test_permanent_refusals_are_not_retried(status):
    model, waits = llm(lambda request: httpx.Response(status, json={"error": "no remaining credits"}))
    with pytest.raises(LLMError) as exc:
        await model.complete(MSG)
    assert exc.value.status == status and not exc.value.retryable and waits == [] and "credits" not in str(exc.value)


async def test_a_malformed_success_is_an_error_and_is_not_retried():
    model, waits = llm(lambda request: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(LLMError) as exc:
        await model.complete(MSG)
    assert not exc.value.retryable and waits == []


async def test_retries_are_counted():
    before = LLM_RETRIES.labels("m", "503")._value.get()
    sequence = iter([httpx.Response(503), httpx.Response(200, json=OK)])
    model, _ = llm(lambda request: next(sequence))
    await model.complete(MSG)
    assert LLM_RETRIES.labels("m", "503")._value.get() == before + 1


# --- concurrency ----------------------------------------------------------------------------
async def test_at_most_max_concurrency_calls_are_in_flight():
    state = {"now": 0, "peak": 0}

    async def handler(request):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        return httpx.Response(200, json=OK)

    model, _ = llm(handler, max_concurrency=2)
    results = await asyncio.gather(*[model.complete(MSG) for _ in range(8)])
    assert len(results) == 8 and state["peak"] == 2


# --- the breaker ----------------------------------------------------------------------------
class Failing:
    def __init__(self, status):
        self.status, self.calls = status, 0

    async def complete(self, messages, **kw):
        self.calls += 1
        raise LLMError("failed", status=self.status)


async def test_provider_trouble_opens_the_circuit_and_later_calls_fail_fast():
    inner = Failing(503)
    guarded = BreakerLLM(inner, CircuitBreaker(failure_threshold=2, reset_seconds=60))
    for _ in range(2):
        with pytest.raises(LLMError):
            await guarded.complete(MSG)
    with pytest.raises(LLMError, match="temporarily unavailable"):
        await guarded.complete(MSG)
    assert inner.calls == 2  # the third call never reached the provider


async def test_a_request_the_provider_rejects_does_not_open_the_circuit():
    inner = Failing(400)
    guarded = BreakerLLM(inner, CircuitBreaker(failure_threshold=2, reset_seconds=60))
    for _ in range(5):
        with pytest.raises(LLMError):
            await guarded.complete(MSG)
    assert inner.calls == 5
    assert not counts_against_provider(LLMError("x", status=422)) and counts_against_provider(LLMError("x", status=402)) and counts_against_provider(LLMError("x"))


# --- routing and fallback -------------------------------------------------------------------
class Recorder:
    """Stands in for OpenAICompatibleLLM: remembers how it was built and fails for models named 'bad-*'."""

    built: list = []

    def __init__(self, base_url, api_key, models, **kw):
        self.base, self.key, self.model, self.kw = base_url, api_key, models["mid"], kw
        Recorder.built.append(self)

    async def complete(self, messages, *, tier="mid", **kw):
        if self.model.startswith("bad"):
            raise LLMError("down", status=503)
        return LLMResult(f"{self.model}@{self.base}", model=self.model)


def settings(**kw):
    base = dict(
        HUGGINGFACE_MODEL="mid-model", LLM_MODEL_CHEAP="cheap-model", LLM_MODEL_REASONING="reason-model",
        LLM_BASE_URL="https://hf.example/v1", HUGGINGFACE_API_KEY="hf-key", LLM_MAX_RETRIES=2, LLM_MAX_CONCURRENCY=8,
        LLM_CHEAP_BASE_URL=None, LLM_CHEAP_API_KEY=None, LLM_MID_BASE_URL=None, LLM_MID_API_KEY=None,
        LLM_REASONING_BASE_URL=None, LLM_REASONING_API_KEY=None,
        LLM_FALLBACK_CHEAP=None, LLM_FALLBACK_MID=None, LLM_FALLBACK_REASONING=None,
    )
    return SimpleNamespace(**{**base, **kw})


async def test_each_tier_goes_to_its_own_model():
    routed = build_llm(settings(), Recorder)
    assert isinstance(routed, RoutedLLM) and routed.tiers == ["cheap", "mid", "reasoning"]
    assert (await routed.complete(MSG, tier="cheap")).text.startswith("cheap-model@")
    assert (await routed.complete(MSG, tier="reasoning")).text.startswith("reason-model@")
    assert (await routed.complete(MSG, tier="mid")).text.startswith("mid-model@")
    assert (await routed.complete(MSG, tier="unheard-of")).text.startswith("mid-model@")


async def test_a_tier_can_use_its_own_endpoint_and_key():
    Recorder.built = []
    routed = build_llm(settings(LLM_CHEAP_BASE_URL="http://ollama:11434/v1", LLM_CHEAP_API_KEY="local"), Recorder)
    assert (await routed.complete(MSG, tier="cheap")).text == "cheap-model@http://ollama:11434/v1"
    assert (await routed.complete(MSG, tier="mid")).text == "mid-model@https://hf.example/v1"
    cheap = next(r for r in Recorder.built if r.model == "cheap-model")
    assert cheap.key == "local" and cheap.kw["retries"] == 2 and cheap.kw["max_concurrency"] == 8 and cheap.kw["timeout"] == 20.0


async def test_the_fallback_model_answers_when_the_primary_fails():
    routed = build_llm(settings(LLM_MODEL_REASONING="bad-reasoner", LLM_FALLBACK_REASONING="backup-model"), Recorder)
    assert (await routed.complete(MSG, tier="reasoning")).text.startswith("backup-model@")
    assert (await routed.complete(MSG, tier="mid")).text.startswith("mid-model@")  # other tiers are untouched


async def test_one_tiers_outage_does_not_stop_the_others():
    routed = build_llm(settings(LLM_MODEL_REASONING="bad-reasoner"), Recorder)  # no fallback configured
    for _ in range(8):  # enough failures to open that tier's circuit
        with pytest.raises(LLMError):
            await routed.complete(MSG, tier="reasoning")
    with pytest.raises(LLMError, match="temporarily unavailable"):
        await routed.complete(MSG, tier="reasoning")
    assert (await routed.complete(MSG, tier="cheap")).text.startswith("cheap-model@")
    assert (await routed.complete(MSG, tier="mid")).text.startswith("mid-model@")


def test_missing_configuration_means_no_model_layer():
    assert build_llm(settings(HUGGINGFACE_MODEL=None), Recorder) is None
    assert build_llm(settings(HUGGINGFACE_API_KEY=None), Recorder) is None
    only_mid = build_llm(settings(LLM_MODEL_CHEAP=None, LLM_MODEL_REASONING=None), Recorder)
    assert only_mid.tiers == ["cheap", "mid", "reasoning"]  # unset tiers share the mid model


def test_a_tier_with_its_own_key_works_without_the_default_key():
    routed = build_llm(settings(HUGGINGFACE_API_KEY=None, LLM_MID_API_KEY="mid-only"), Recorder)
    assert routed.tiers == ["mid"]


def test_fake_llm_still_satisfies_the_interface():
    assert FakeLLM(["x"]).replies == ["x"]
