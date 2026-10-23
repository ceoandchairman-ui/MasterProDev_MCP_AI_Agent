"""The compression tier: summaries, episode lines and consolidation use their own model setting; everything else does not."""

import json
from types import SimpleNamespace

import pytest

from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.llm.client import TIERS, LLMError, LLMResult
from mpd_assistant.core.llm.factory import build_llm
from mpd_assistant.memory.consolidation import Consolidator
from mpd_assistant.memory.episodic import EpisodeWriter
from mpd_assistant.memory.long_term.store import MAX_TEXT, MemoryStore
from mpd_assistant.memory.pipeline import MemoryWiring
from mpd_assistant.memory.short_term.summary import RollingSummarizer

MSG = [{"role": "user", "content": "q"}]


class Recorder:
    """Records the tier of every call and answers with something each caller accepts."""

    def __init__(self, reply="A short summary."):
        self.reply, self.tiers = reply, []

    async def complete(self, messages, *, tier="mid", **kw):
        self.tiers.append(tier)
        return LLMResult(self.reply)


def turns(n):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i} about the booking app"} for i in range(n)]


# --- the callers ----------------------------------------------------------------------------
async def test_the_rolling_summary_uses_the_compress_tier():
    llm = Recorder("The user wants a booking app.")
    assert await RollingSummarizer(llm, MemoryKV(), every=2).maybe_update("t1", turns(10))
    assert llm.tiers == ["compress"]


async def test_the_episode_line_uses_the_compress_tier():
    llm = Recorder(json.dumps({"text": "The user wanted a booking app."}))
    writer = EpisodeWriter(MemoryStore(), None, lambda user: True, MemoryKV(), llm)
    assert await writer._condense("x" * (MAX_TEXT + 50)) == "The user wanted a booking app."
    assert llm.tiers == ["compress"]


async def test_consolidation_uses_the_compress_tier():
    llm = Recorder(json.dumps({"text": "Runs a logistics company.", "importance": 0.7, "confidence": 0.8}))
    consolidator = Consolidator(MemoryStore(), llm, lambda user: True, lambda: 0.0)
    candidate = await consolidator._distill([SimpleNamespace(text="runs a logistics company"), SimpleNamespace(text="logistics firm")])
    assert candidate is not None and candidate.text == "Runs a logistics company." and llm.tiers == ["compress"]


async def test_per_turn_memory_extraction_stays_on_the_cheap_tier():
    llm = Recorder(json.dumps({"memories": []}))
    await MemoryWiring(MemoryStore(), llm, lambda user: True).after("u1", "We run a logistics company with forty trucks across Ontario", allow=True)
    assert llm.tiers == ["cheap"]  # extraction is per message and latency-sensitive; only the summarising jobs moved


# --- the factory ----------------------------------------------------------------------------
class Built:
    made = []

    def __init__(self, base_url, api_key, models, **kw):
        self.base, self.key, self.model = base_url, api_key, models["mid"]
        Built.made.append(self)

    async def complete(self, messages, *, tier="mid", **kw):
        if self.model.startswith("bad"):
            raise LLMError("down", status=503)
        return LLMResult(f"{self.model}@{self.base}", model=self.model)


def settings(**kw):
    base = dict(
        HUGGINGFACE_MODEL="mid-model", LLM_MODEL_CHEAP="cheap-model", LLM_MODEL_REASONING="reason-model",
        LLM_BASE_URL="https://hf.example/v1", HUGGINGFACE_API_KEY="hf-key", LLM_MAX_RETRIES=2, LLM_MAX_CONCURRENCY=8,
    )
    return SimpleNamespace(**{**base, **kw})


def test_compress_is_a_tier():
    assert "compress" in TIERS


async def test_without_its_own_model_compress_shares_the_cheap_model():
    routed = build_llm(settings(), Built)
    assert (await routed.complete(MSG, tier="compress")).text.startswith("cheap-model@")


async def test_without_a_cheap_model_either_it_falls_back_to_the_mid_model():
    routed = build_llm(settings(LLM_MODEL_CHEAP=None), Built)
    assert (await routed.complete(MSG, tier="compress")).text.startswith("mid-model@")


async def test_its_own_model_endpoint_and_key_are_used_for_compress_only():
    Built.made = []
    routed = build_llm(settings(LLM_MODEL_COMPRESS="summary-model", LLM_COMPRESS_BASE_URL="http://gpu:8000/v1", LLM_COMPRESS_API_KEY="local"), Built)
    assert (await routed.complete(MSG, tier="compress")).text == "summary-model@http://gpu:8000/v1"
    assert (await routed.complete(MSG, tier="cheap")).text == "cheap-model@https://hf.example/v1"  # the other tiers are untouched
    compress = next(b for b in Built.made if b.model == "summary-model")
    assert compress.key == "local"


async def test_a_fallback_model_covers_an_outage_of_the_compression_model():
    routed = build_llm(settings(LLM_MODEL_COMPRESS="bad-summarizer", LLM_FALLBACK_COMPRESS="backup-summarizer"), Built)
    assert (await routed.complete(MSG, tier="compress")).text.startswith("backup-summarizer@")


async def test_an_outage_of_the_compression_model_does_not_stop_conversation_models():
    routed = build_llm(settings(LLM_MODEL_COMPRESS="bad-summarizer"), Built)
    for _ in range(8):
        with pytest.raises(LLMError):
            await routed.complete(MSG, tier="compress")
    with pytest.raises(LLMError, match="temporarily unavailable"):
        await routed.complete(MSG, tier="compress")  # its circuit is open
    assert (await routed.complete(MSG, tier="mid")).text.startswith("mid-model@")
    assert (await routed.complete(MSG, tier="cheap")).text.startswith("cheap-model@")


async def test_a_failed_summary_call_never_breaks_a_conversation():
    class Down:
        async def complete(self, messages, **kw):
            raise LLMError("down", status=503)

    assert not await RollingSummarizer(Down(), MemoryKV(), every=2).maybe_update("t1", turns(10))  # skipped quietly, tried again next turn
