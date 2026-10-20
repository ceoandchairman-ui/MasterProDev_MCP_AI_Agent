"""Context management: recent turns in prompts, standalone search queries for follow-ups, budgeted background notes,
and the prompt registry that now covers every prompt."""

import json

import pytest

from mpd_assistant.agents.common import memory_note
from mpd_assistant.agents.comms_scheduling.agent import make_comms
from mpd_assistant.agents.concierge.agent import make_concierge, standalone_question
from mpd_assistant.agents.context import HISTORY_BUDGET, needs_rewrite, recent_turns
from mpd_assistant.agents.lead_conversion.agent import MemoryLeadRepository, make_lead_conversion
from mpd_assistant.agents.prompts import prompt_versions
from mpd_assistant.core.llm.client import LLMError, LLMResult
from mpd_assistant.memory.short_term.window import estimate_tokens
from mpd_assistant.retrieval.hybrid import Hit
from mpd_assistant.tools.executor import ToolExecutor
from mpd_assistant.tools.registry import default_registry


def msg(role, content, **extra):
    return {"role": role, "content": content, **extra}


HISTORY = [
    msg("user", "What services do you offer?"),
    msg("assistant", "We build custom mobile apps and web platforms."),
    msg("user", "How much does a mobile app cost?"),
    msg("assistant", "Pricing depends on scope."),
]


def state(*extra, **kw):
    return {"messages": [*HISTORY, *extra], "language": "en", "session_id": "s1", **kw}


# --- recent turns ---------------------------------------------------------------------------
def test_recent_turns_are_the_earlier_messages_without_the_current_one():
    current = msg("user", "And how long does it take?")
    turns = recent_turns(state(current), 600)
    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant"]
    assert turns[-1]["content"] == "Pricing depends on scope." and all(t["content"] != current["content"] for t in turns)


def test_synthetic_system_tool_and_empty_messages_are_left_out():
    current = msg("user", "ok?")
    noisy = [msg("user", "part one", synthetic=True), msg("system", "internal"), msg("tool", "result"), msg("assistant", "   "), *HISTORY[:2]]
    turns = recent_turns({"messages": [*noisy, current]}, 600)
    assert [t["content"] for t in turns] == [HISTORY[0]["content"], HISTORY[1]["content"]]


def test_the_window_is_trimmed_to_the_budget_keeping_the_newest():
    long = [msg("user" if i % 2 == 0 else "assistant", f"turn {i} " + "word " * 120) for i in range(10)]
    turns = recent_turns({"messages": [*long, msg("user", "now?")]}, 200)
    assert 0 < len(turns) < 8 and sum(estimate_tokens(t["content"]) for t in turns) <= 260
    assert turns[-1]["content"].startswith("turn 9")  # the most recent turn survived
    assert recent_turns({"messages": [*long, msg("user", "now?")]}, 600, max_turns=3).__len__() <= 3


def test_no_history_means_no_turns():
    assert recent_turns({"messages": [msg("user", "hello")]}, 600) == [] and recent_turns({}, 600) == []


# --- follow-up detection --------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    ["And how long does it take?", "what about the second one", "How much is that?", "Why?", "and for a website", "Et pour le site web ?", "Combien ça coûte ?", "Can they integrate with Stripe payments today"],
)
def test_follow_ups_are_detected(text):
    assert needs_rewrite(text, True)


@pytest.mark.parametrize("text", ["What programming languages does your development team use for mobile projects?", "Tell me about your cloud migration and architecture audit services"])
def test_self_contained_questions_are_left_alone(text):
    assert not needs_rewrite(text, True)


@pytest.mark.parametrize(
    "text",
    [
        "And what about pricing for a really long detailed question here please",
        "Also tell me about your cloud migration services in detail please",
        "Alors quels sont vos tarifs pour une application mobile complete",
    ],
)
def test_long_follow_ups_are_caught_by_their_opening_words_alone(text):
    # Too long for the short-message rule and without a pronoun: only the opening-word rule can catch these.
    assert len(text.split()) > 6 and needs_rewrite(text, True)


def test_a_word_that_merely_starts_like_an_opener_is_not_one():
    assert not needs_rewrite("Etape suivante pour la migration cloud de notre entreprise", True)


def test_without_history_nothing_is_rewritten():
    assert not needs_rewrite("And how long does it take?", False)


# --- the budgeted background note -----------------------------------------------------------
def note_state(**kw):
    base = {
        "thread_summary": "The user wants a booking app.",
        "memory_context": "- runs a logistics firm\n- prefers short answers\n- uses Stripe",
        "context_notes": "Referenced earlier in this conversation: email m123. ",
        "attachment_context": "FILE brief.txt: " + "details " * 200,
        "style_examples": "Example reply: " + "style " * 100,
    }
    return {**base, **kw}


def test_without_a_budget_the_note_is_exactly_what_it_always_was():
    text = memory_note(note_state())
    assert text.startswith("Earlier in this conversation:\nThe user wants a booking app.\n\nKnown about the user (from earlier conversations):\n- runs a logistics firm")
    assert "Referenced earlier" in text and "Files the user shared" in text and text.endswith("\n\n")
    assert memory_note({}) == ""


def test_a_generous_budget_keeps_everything():
    text = memory_note(note_state(), 5000)
    for part in ("booking app", "logistics firm", "uses Stripe", "email m123", "FILE brief.txt", "Example reply"):
        assert part in text


def test_a_tight_budget_drops_files_and_style_first_but_never_the_references():
    text = memory_note(note_state(), 120)
    assert "FILE brief.txt" not in text and "Example reply" not in text
    assert "email m123" in text and "booking app" in text
    assert estimate_tokens(text) <= 120


def test_memories_are_cut_line_by_line_best_match_first():
    text = memory_note(note_state(attachment_context="", style_examples="", context_notes=""), 40)
    assert "runs a logistics firm" in text and "uses Stripe" not in text  # the first (best) line is kept, the last is dropped


def test_an_empty_state_gives_an_empty_note_even_with_a_budget():
    assert memory_note({}, 500) == ""


# --- the agents -----------------------------------------------------------------------------
class Scripted:
    """Answers in order and records (tier, messages) for every call."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def complete(self, messages, *, tier="mid", **kw):
        self.calls.append((tier, messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResult(reply)


class Retriever:
    def __init__(self):
        self.queries = []

    async def search(self, query):
        self.queries.append(query)
        return [Hit("1", "A typical mobile app project takes 12 to 16 weeks from discovery to launch.", "process.txt", 0.9)]


async def test_a_follow_up_is_searched_as_a_standalone_question_and_answered_with_the_history():
    llm, retriever = Scripted(["How long does a mobile app project take?", "Usually 12 to 16 weeks."]), Retriever()
    out = await make_concierge(llm, retriever)(state(msg("user", "And how long does it take?")))
    assert retriever.queries == ["How long does a mobile app project take?"]
    (rewrite_tier, rewrite_msgs), (answer_tier, answer_msgs) = llm.calls
    assert rewrite_tier == "cheap" and "Latest message: And how long does it take?" in rewrite_msgs[1]["content"]
    assert answer_tier == "mid" and [m["role"] for m in answer_msgs] == ["system", "user", "assistant", "user", "assistant", "user"]
    assert answer_msgs[-1]["content"].endswith("Question: And how long does it take?")  # the user's own words, not the rewrite
    assert "12 to 16 weeks" in out["response"] and "process.txt" in out["response"]


async def test_a_self_contained_question_costs_no_extra_model_call():
    llm, retriever = Scripted(["Usually 12 to 16 weeks."]), Retriever()
    await make_concierge(llm, retriever)(state(msg("user", "How long does a typical mobile app project take from discovery to launch?")))
    assert len(llm.calls) == 1 and retriever.queries == ["How long does a typical mobile app project take from discovery to launch?"]


async def test_the_first_message_of_a_conversation_is_never_rewritten():
    llm, retriever = Scripted(["ok"]), Retriever()
    await make_concierge(llm, retriever)({"messages": [msg("user", "And how long does it take?")], "language": "en"})
    assert len(llm.calls) == 1 and retriever.queries == ["And how long does it take?"]


@pytest.mark.parametrize("bad", [LLMError("down"), "", "   ", '{"question": "x"}', "word " * 200])
async def test_a_bad_rewrite_falls_back_to_the_original_message(bad):
    llm = Scripted([bad])
    assert await standalone_question(llm, recent_turns(state(msg("user", "x")), 600), "And how long does it take?") == "And how long does it take?"


async def test_a_rewrite_is_cleaned_of_quotes_and_extra_lines():
    llm = Scripted(['"How long does a mobile app project take?"\nExplanation: resolved "it".'])
    assert await standalone_question(llm, recent_turns(state(msg("user", "x")), 600), "and how long?") == "How long does a mobile app project take?"


async def test_the_comms_planner_sees_the_recent_turns():
    llm = Scripted([json.dumps({"steps": []})])

    async def backend(tool, args):
        return {"status": "success"}

    run = make_comms(llm, ToolExecutor(default_registry(), backend), default_registry())
    earlier = [msg("user", "Book a call on 2026-11-03 at 2pm"), msg("assistant", "Done. Booked for 2pm.")]
    await run({"messages": [*earlier, msg("user", "actually make it 3pm")], "language": "en", "session_id": "s1", "user_id": "u1"})
    _, messages = llm.calls[0]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"] and messages[1]["content"] == "Book a call on 2026-11-03 at 2pm"
    assert messages[-1]["content"] == "actually make it 3pm"


async def test_lead_extraction_sees_what_the_assistant_just_asked():
    llm = Scripted([json.dumps({"need": None, "timeline": "March", "budget": None, "company": None})])
    leads = MemoryLeadRepository()
    earlier = [msg("user", "We need a booking app"), msg("assistant", "Great. When do you need it by?")]
    out = await make_lead_conversion(llm, leads)({"messages": [*earlier, msg("user", "March")], "language": "en", "user_id": "u1", "lead_stage": "new", "lead_slots": {}})
    _, messages = llm.calls[0]
    assert messages[-2]["content"] == "Great. When do you need it by?" and messages[-1]["content"] == "March"
    assert out["lead_slots"]["timeline"] == "March"


def test_history_budgets_are_small_enough_for_the_cheap_tier():
    assert HISTORY_BUDGET["concierge"] <= 600 and HISTORY_BUDGET["lead"] <= HISTORY_BUDGET["comms"] <= HISTORY_BUDGET["concierge"]


# --- the prompt registry --------------------------------------------------------------------
def test_every_prompt_is_registered_with_a_version():
    versions = prompt_versions()
    expected = {
        "comms_scheduling/planner", "concierge/system", "concierge/rewrite", "lead_conversion/extract", "quote/system", "solution_architect/system",
        "evaluator/judge", "memory/summarize", "memory/propose", "memory/consolidate", "memory/condense",
    }
    assert expected <= set(versions) and all(versions[k] for k in expected)


def test_moved_prompts_keep_their_wording_and_literal_json_braces():
    from mpd_assistant.evaluation.online.judge import SYSTEM as judge
    from mpd_assistant.memory.consolidation import SYSTEM as consolidate
    from mpd_assistant.memory.episodic import CONDENSE_SYSTEM as condense
    from mpd_assistant.memory.pipeline import PROPOSE_SYSTEM as propose
    from mpd_assistant.memory.short_term.summary import SYSTEM as summarize

    assert judge.startswith("You are a strict fact checker") and '{"supported": number between 0 and 1' in judge
    assert "durable facts" in propose and '{"memories": []}' in propose and "{{" not in propose
    assert '{"text": ""}' in consolidate and condense.endswith('{"text": str}.') and summarize.endswith("Do not invent anything.")
