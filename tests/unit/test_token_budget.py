import asyncio

import pytest
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.agents.factory import build_runners
from mpd_assistant.core import crypto
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.llm.budget import BudgetExceeded, TokenBudget, current_scope, reset_scope, set_scope
from mpd_assistant.core.llm.client import LLMResult
from mpd_assistant.core.llm.metered import MeteredLLM
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.retrieval.hybrid import Hit
from mpd_assistant.tools.registry import default_registry


class Costly:
    """Every call costs 100 tokens."""

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, **kwargs):
        self.calls += 1
        return LLMResult("An answer.", tokens_in=60, tokens_out=40)


class Retriever:
    async def search(self, query):
        return [Hit("1", "MasterProDev builds custom software.", "about.txt", 0.9)]


def test_budget_counts_per_scope_and_globally():
    b = TokenBudget(MemoryKV(), per_scope_daily=250, global_daily=400)
    b.record("a", 200)
    assert b.exhausted("a") is None
    b.record("a", 100)
    assert b.exhausted("a") == "session" and b.exhausted("b") is None
    b.record("b", 150)
    assert b.exhausted("b") == "global"  # 450 used in total, past the global cap


def test_check_raises_a_budget_error_that_agents_already_handle():
    b = TokenBudget(MemoryKV(), per_scope_daily=10, global_daily=0)
    b.record("a", 10)
    with pytest.raises(BudgetExceeded) as exc:
        b.check("a")
    assert exc.value.which == "session"
    b.check("other")  # a different conversation is unaffected


async def test_metered_llm_charges_the_active_conversation_and_stops_when_spent():
    budget = TokenBudget(MemoryKV(), per_scope_daily=250, global_daily=0)
    inner = Costly()
    llm = MeteredLLM(inner, "concierge", budget)
    marker = set_scope("conv-1")
    try:
        for _ in range(3):
            await llm.complete([{"role": "user", "content": "x"}])
        with pytest.raises(BudgetExceeded):
            await llm.complete([{"role": "user", "content": "x"}])
    finally:
        reset_scope(marker)
    assert inner.calls == 3 and current_scope() is None


async def test_concurrent_conversations_do_not_share_a_budget_scope():
    budget = TokenBudget(MemoryKV(), per_scope_daily=150, global_daily=0)
    llm = MeteredLLM(Costly(), "concierge", budget)

    async def converse(name, turns):
        marker = set_scope(name)
        try:
            for _ in range(turns):
                await asyncio.sleep(0)
                await llm.complete([{"role": "user", "content": "x"}])
        finally:
            reset_scope(marker)

    await asyncio.gather(converse("a", 1), converse("b", 1))
    assert budget.exhausted("a") is None and budget.exhausted("b") is None
    await converse("a", 1)
    assert budget.exhausted("a") == "session" and budget.exhausted("b") is None


def service(budget):
    llm = Costly()
    runners = build_runners(llm, Retriever(), None, default_registry(), budget=budget)
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    return ChatService(build_graph(runners, checkpointer=MemorySaver()), vault, budget=budget), llm


async def test_chat_stops_before_calling_the_model_once_the_conversation_budget_is_spent():
    budget = TokenBudget(MemoryKV(), per_scope_daily=150, global_daily=0)
    svc, llm = service(budget)
    first = await svc.chat("s1", "Tell me about your mobile app work for logistics companies")
    second = await svc.chat("s1", "And what about your web platform work for retail companies")
    blocked = await svc.chat("s1", "One more question about cloud migration services please")
    assert first.reply.startswith("An answer") and second.reply.startswith("An answer")
    assert "daily limit" in blocked.reply and blocked.eval_reasons == ["budget_session"] and llm.calls == 2


async def test_global_cap_shows_a_busy_message_to_everyone_but_never_blocks_templates_or_a_human_request():
    budget = TokenBudget(MemoryKV(), per_scope_daily=0, global_daily=100)
    svc, llm = service(budget)
    await svc.chat("s1", "Tell me about your mobile app work for logistics companies")
    other = await svc.chat("s2", "Tell me about your web platform work for retail companies")
    assert "very busy" in other.reply and other.eval_reasons == ["budget_global"]
    assert (await svc.chat("s3", "hello")).reply.startswith("Hello")  # templated: costs no tokens
    person = await svc.chat("s4", "I want to speak to a real person", verified=True)
    assert person.escalated and llm.calls == 1


async def test_a_spent_budget_inside_an_agent_degrades_to_the_safe_message():
    budget = TokenBudget(MemoryKV(), per_scope_daily=100, global_daily=0)
    svc, llm = service(budget)
    budget.record("s9", 50)
    ok = await svc.chat("s9", "Tell me about your mobile app work for logistics companies")  # 100 tokens, now exactly spent
    assert ok.reply.startswith("An answer")
    after = await svc.chat("s9", "Tell me about your web platform work for retail companies")
    assert "daily limit" in after.reply
