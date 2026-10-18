import json

from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.agents.factory import build_runners
from mpd_assistant.cache.store import MemoryBackend, ResponseCache
from mpd_assistant.core import crypto
from mpd_assistant.core.llm.client import FakeLLM, LLMResult
from mpd_assistant.evaluation.online.judge import LlmJudge
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.retrieval.hybrid import Hit
from mpd_assistant.tools.registry import default_registry


class Retriever:
    async def search(self, query):
        return [Hit("1", "MasterProDev builds custom software in Toronto.", "about.txt", 0.9)]


class Answerer:
    def __init__(self, answer="We build custom software."):
        self.answer = answer

    async def complete(self, messages, **kwargs):
        return LLMResult(self.answer)


def verdict(score, issues=()):
    return json.dumps({"supported": score, "issues": list(issues)})


def service(judge_replies, rate=1.0, answer="We build custom software.", cache=None):
    judge_llm = FakeLLM(judge_replies)
    judge = LlmJudge(judge_llm, sample_rate=rate, rng=lambda: 0.0)
    runners = build_runners(Answerer(answer), Retriever(), None, default_registry())
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    graph = build_graph(runners, checkpointer=MemorySaver(), judge=judge)
    return ChatService(graph, vault, cache=cache), judge_llm


async def test_supported_answers_pass_through_unchanged():
    svc, judge_llm = service([verdict(0.95)])
    out = await svc.chat("s1", "Tell me about your software work in Toronto please")
    assert out.reply.startswith("We build custom software") and len(judge_llm.calls) == 1
    assert "EVIDENCE" in judge_llm.calls[0][1]["content"] and "Toronto" in judge_llm.calls[0][1]["content"]


async def test_unsupported_claims_are_replaced_by_the_safe_reply():
    svc, _ = service([verdict(0.1, ["claims 200 employees, not in the evidence"])], answer="We have 200 employees and an office in Paris.")
    out = await svc.chat("s1", "Tell me about your company size and offices please")
    assert "find a reliable answer" in out.reply and "unsupported_claim" in out.eval_reasons and "200 employees" not in out.reply


async def test_unsampled_turns_cost_nothing():
    svc, judge_llm = service([verdict(0.0)], rate=0.0)
    out = await svc.chat("s1", "Tell me about your software work in Toronto please")
    assert out.reply.startswith("We build custom software") and judge_llm.calls == []


async def test_judge_failures_never_change_the_reply():
    for replies in ([], ["not json at all"], [json.dumps({"supported": "high"})]):
        svc, _ = service(replies)
        out = await svc.chat("s1", "Tell me about your software work in Toronto please")
        assert out.reply.startswith("We build custom software")


async def test_judged_down_answers_are_not_cached_but_supported_ones_are():
    cache = ResponseCache(MemoryBackend())
    bad, _ = service([verdict(0.1)], cache=cache)
    await bad.chat("a", "What services do you offer?")
    good, judge_llm = service([verdict(0.9)], cache=cache)
    first = await good.chat("b", "What services do you offer?")
    again = await good.chat("c", "What services do you offer?")
    assert first.reply.startswith("We build") and again.cache_hit and len(judge_llm.calls) == 1


async def test_evidence_from_one_turn_is_not_judged_against_the_next_answer():
    svc, judge_llm = service([verdict(0.9), verdict(0.9)])
    await svc.chat("s1", "Tell me about your software work in Toronto please")
    await svc.chat("s1", "hello")  # templated greeting: no evidence, so no judge call
    assert len(judge_llm.calls) == 1
