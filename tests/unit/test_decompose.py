from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.core import crypto
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.routing.decompose import split_tasks
from mpd_assistant.routing.intents import Agent

COMPOUND = "I need a quote for a new website and also book a call with your team"


def test_compound_requests_split_by_owning_agent():
    assert split_tasks(COMPOUND, verified=True) == ["I need a quote for a new website", "book a call with your team"]


def test_same_agent_questions_are_not_split():
    text = "What services do you offer? Where are you located?"
    assert split_tasks(text) == [text]


def test_asking_for_a_person_is_never_split():
    text = "I need a quote for a website. Also let me talk to a human"
    assert split_tasks(text, verified=True) == [text]


def test_short_fragments_and_plain_sentences_stay_whole():
    for text in ["hello", "Do you build apps then?", "quote"]:
        assert split_tasks(text) == [text]


def test_at_most_three_tasks():
    text = "Send an email to the team. Book a call tomorrow. I need a quote. What services do you offer?"
    assert len(split_tasks(text, verified=True)) <= 3


def service():
    async def quote(state):
        return {"response": "QUOTE-REPLY"}

    async def comms(state):
        return {"response": "CALL-REPLY"}

    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    graph = build_graph({Agent.QUOTE: quote, Agent.COMMS_SCHEDULING: comms}, checkpointer=MemorySaver())
    return ChatService(graph, vault)


async def test_each_part_reaches_its_agent_and_replies_are_joined():
    out = await service().chat("s1", COMPOUND, verified=True, user_id="u1")
    assert out.reply.index("QUOTE-REPLY") < out.reply.index("CALL-REPLY")
    assert not out.escalated


async def test_unverified_visitor_gets_one_identity_prompt_not_two():
    out = await service().chat("s2", COMPOUND, verified=False)
    assert out.reply.count("verify who you are") == 1


async def test_task_state_does_not_leak_into_the_next_turn():
    svc = service()
    await svc.chat("s3", COMPOUND, verified=True, user_id="u1")
    again = await svc.chat("s3", "I need a quote for a mobile app", verified=True, user_id="u1")
    assert again.reply == "QUOTE-REPLY"
