"""Leak canaries: planted personal values must never appear in logs, the key-value store, or checkpoints."""

import json
import logging

import pytest
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.agents.factory import build_runners
from mpd_assistant.core import crypto
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.llm.client import FakeLLM
from mpd_assistant.core.logging import JsonFormatter
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.privacy.kv_store import KvVaultStore
from mpd_assistant.privacy.vault import PiiVault
from mpd_assistant.retrieval.hybrid import Hit
from mpd_assistant.tools.executor import ToolExecutor
from mpd_assistant.tools.registry import default_registry

CANARIES = ["canary.ann@example.com", "+14165550199", "4111 1111 1111 1111", "123 456 789"]


class StubRetriever:
    async def search(self, query):
        return [Hit("1", "We build software for clients.", "about.txt", 0.9)]


@pytest.fixture
def stack():
    kv = MemoryKV()
    cipher = crypto.FieldCipher(crypto.generate_key())
    vault = PiiVault(cipher, KvVaultStore(kv))
    registry = default_registry()
    executor = ToolExecutor(registry, lambda t, a: None)

    async def unused(tool, args):
        return {}

    executor = ToolExecutor(registry, unused, rehydrate=vault.detokenize, pseudonymize=vault.tokenize)
    # The model echoes whatever tokens it was given, which is the realistic failure mode to test.
    llm = FakeLLM(["Noted, I will reply to the token you were given." for _ in range(10)])
    runners = build_runners(llm, StubRetriever(), executor, registry)
    graph = build_graph(runners, checkpointer=MemorySaver())
    return ChatService(graph, vault), kv, graph


async def test_canaries_never_reach_the_store_or_checkpoint(stack, caplog):
    svc, kv, graph = stack
    caplog.set_level(logging.DEBUG)
    text = f"Hi, I am {CANARIES[0]}, phone {CANARIES[1]}, card {CANARIES[2]}, SIN {CANARIES[3]}. What do you do?"
    await svc.chat("canary-s1", text, verified=True, user_id="u1")

    dump = json.dumps(kv._data, default=str)
    state = await graph.aget_state({"configurable": {"thread_id": "canary-s1"}})
    checkpoint = json.dumps(state.values, default=str)
    logs = "\n".join(JsonFormatter().format(r) for r in caplog.records)
    for value in CANARIES:
        assert value not in dump, f"{value} found in key-value store"
        assert value not in checkpoint, f"{value} found in checkpoint"
        assert value not in logs, f"{value} found in logs"


async def test_canary_survives_round_trip_only_for_the_same_session(stack):
    svc, kv, _ = stack
    await svc.chat("canary-s2", f"Mail {CANARIES[0]} please", verified=True, user_id="u1")
    assert svc._vault.detokenize("canary-s2", "<EMAIL_1>") == CANARIES[0]
    assert svc._vault.detokenize("canary-other", "<EMAIL_1>") == "<EMAIL_1>"
