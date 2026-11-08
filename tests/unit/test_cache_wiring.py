from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.agents.factory import build_runners
from mpd_assistant.cache.store import MemoryBackend, ResponseCache
from mpd_assistant.core import crypto
from mpd_assistant.core.llm.client import FakeLLM
from mpd_assistant.core.llm.metered import MeteredLLM
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import CacheSettings, ChatService
from mpd_assistant.observability import metrics
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.retrieval.hybrid import Hit
from mpd_assistant.tools.registry import default_registry


class Retriever:
    async def search(self, query):
        return [Hit("1", "MasterProDev builds custom software.", "about.txt", 0.9)]


def service(llm, cache=None, versions=None):
    runners = build_runners(llm, Retriever(), None, default_registry())
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    return ChatService(build_graph(runners, checkpointer=MemorySaver()), vault, cache=cache, cache_settings=versions or CacheSettings())


async def test_repeat_faq_is_served_from_cache_without_calling_the_model():
    llm = FakeLLM(["We build custom software."])
    svc = service(llm, ResponseCache(MemoryBackend()))
    first = await svc.chat("a", "What services do you offer?")
    second = await svc.chat("b", "what services do you offer")  # another visitor, same question
    assert not first.cache_hit and second.cache_hit
    assert second.reply == first.reply and len(llm.calls) == 1


async def test_questions_with_personal_data_or_tokens_are_never_cached():
    llm = FakeLLM(["Noted.", "Noted again."])
    cache = ResponseCache(MemoryBackend())
    svc = service(llm, cache)
    await svc.chat("a", "What services do you offer? Reply to ann@example.com")
    again = await svc.chat("b", "What services do you offer? Reply to ann@example.com")
    assert not again.cache_hit and len(llm.calls) == 2


async def test_gated_and_side_effect_intents_skip_the_cache():
    llm = FakeLLM([])
    svc = service(llm, ResponseCache(MemoryBackend()))
    one = await svc.chat("a", "How much would a website cost?", verified=False)
    two = await svc.chat("b", "How much would a website cost?", verified=False)
    assert "verify" in one.reply.lower() and not two.cache_hit


async def test_prompt_or_corpus_version_bump_invalidates_entries():
    cache = ResponseCache(MemoryBackend())
    llm = FakeLLM(["v1 answer", "v2 answer"])
    old = service(llm, cache, CacheSettings(prompt_version="v1", corpus_version="1"))
    new = service(llm, cache, CacheSettings(prompt_version="v2", corpus_version="1"))
    assert (await old.chat("a", "What services do you offer?")).reply.startswith("v1 answer")
    assert (await new.chat("b", "What services do you offer?")).reply.startswith("v2 answer")


async def test_failed_evaluation_is_not_cached():
    llm = FakeLLM(["TOOL: send_email now", "A clean answer."])
    svc = service(llm, ResponseCache(MemoryBackend()))
    bad = await svc.chat("a", "What services do you offer?")
    good = await svc.chat("b", "What services do you offer?")
    assert "try again" in bad.reply.lower() and not good.cache_hit and good.reply.startswith("A clean answer")


async def test_tokens_are_counted_per_agent():
    before = metrics.TOKENS.labels("concierge", "in")._value.get()
    llm = MeteredLLM(FakeLLM(["short answer"]), "concierge")
    await llm.complete([{"role": "user", "content": "x" * 400}])
    assert metrics.TOKENS.labels("concierge", "in")._value.get() > before
