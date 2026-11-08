from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.core import crypto
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault


def service():
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    return ChatService(build_graph({}, checkpointer=MemorySaver()), vault)


async def test_long_conversations_never_hit_the_step_guard():
    svc = service()
    for i in range(15):
        out = await svc.chat("long", f"What services do you offer for project number {i}?")
        assert not out.escalated, f"escalated on turn {i + 1}"


async def test_escalation_flag_does_not_carry_into_later_turns():
    svc = service()
    first = await svc.chat("s", "I want to speak to a human please")
    assert first.escalated
    later = await svc.chat("s", "What services do you offer?")
    assert not later.escalated
