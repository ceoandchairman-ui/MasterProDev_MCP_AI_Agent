from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.agents.common import memory_note
from mpd_assistant.agents.factory import build_runners
from mpd_assistant.business.escalations import EscalationFlow, EscalationService
from mpd_assistant.core import crypto
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.llm.client import LLMResult
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.handoff import build_packet
from mpd_assistant.graph.service import ChatService
from mpd_assistant.memory.short_term.summary import KEEP_RECENT, RollingSummarizer
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.retrieval.hybrid import Hit
from mpd_assistant.tools.registry import default_registry


def messages(n):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"} for i in range(n)]


class Summarizing:
    def __init__(self, text="User wants a logistics app; budget unknown."):
        self.calls, self.text = [], text

    async def complete(self, msgs, **kwargs):
        self.calls.append(msgs)
        return LLMResult(self.text)


async def test_summary_only_refreshes_after_enough_new_messages():
    llm, kv = Summarizing(), MemoryKV()
    s = RollingSummarizer(llm, kv, every=8)
    assert not await s.maybe_update("t", messages(10))  # too short
    assert await s.maybe_update("t", messages(8 + KEEP_RECENT))
    assert s.context_for("t").startswith("User wants a logistics app")
    assert not await s.maybe_update("t", messages(8 + KEEP_RECENT + 3))  # not enough new material yet
    assert await s.maybe_update("t", messages(16 + KEEP_RECENT))
    assert "Previous summary" in llm.calls[-1][1]["content"]


async def test_summary_failure_leaves_the_old_summary_in_place():
    class Down:
        async def complete(self, *a, **k):
            from mpd_assistant.core.llm.client import LLMError

            raise LLMError("down")

    kv = MemoryKV()
    kv.set("summary:t", {"text": "old", "upto": 0}, 60)
    assert not await RollingSummarizer(Down(), kv, every=2).maybe_update("t", messages(12))
    assert RollingSummarizer(Down(), kv).context_for("t") == "old"


def test_summary_and_memories_both_reach_the_prompt_helper():
    note = memory_note({"thread_summary": "They want an app.", "memory_context": "- runs a logistics company"})
    assert note.index("They want an app.") < note.index("runs a logistics company")
    assert memory_note({}) == ""


class Retriever:
    async def search(self, query):
        return [Hit("1", "MasterProDev builds custom software.", "about.txt", 0.9)]


async def test_long_conversation_gets_summarized_and_fed_back_to_the_agent():
    llm = Summarizing("Earlier: the user asked about mobile apps.")
    registry = default_registry()
    runners = build_runners(llm, Retriever(), None, registry)
    kv = MemoryKV()
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    svc = ChatService(build_graph(runners, checkpointer=MemorySaver()), vault, summarizer=RollingSummarizer(llm, kv, every=4))
    for i in range(7):
        await svc.chat("t1", f"Tell me about your mobile app work, question number {i}")
    assert "mobile apps" in RollingSummarizer(llm, kv).context_for("t1")
    await svc.chat("t1", "And what about web platforms for logistics, one more question")
    answers = [c for c in llm.calls if "Answer ONLY from the provided context" in c[0]["content"]]
    assert "Earlier in this conversation" in answers[-1][-1]["content"]  # the final user message carries the summary; earlier turns sit before it


def test_handoff_packet_lists_known_and_missing_facts_within_the_cap():
    packet = build_packet({"intent": "project_inquiry", "lead_stage": "engaged", "lead_slots": {"need": "mobile app"}, "language": "fr",
                           "pending_action": {"tool": "create_calendar_event"}})
    assert "Need: mobile app" in packet and "Still unknown: timeline, budget" in packet and "create_calendar_event" in packet
    assert len(build_packet({"intent": "x" * 5000})) <= 900


async def test_staff_summary_leads_with_the_handoff_packet():
    service = EscalationService()
    flow = EscalationFlow(service, None, None)
    ref = await flow.hook({"session_row": "s1", "messages": [{"role": "user", "content": "I need help"}], "intent": "human_request",
                           "lead_stage": "qualified", "lead_slots": {"need": "mobile app", "timeline": "March", "budget": "40k"}}, "human_request")
    summary = service._repo.get(ref).summary
    assert summary.startswith("Intent: human_request") and "Budget: 40k" in summary and "user: I need help" in summary
