import pytest
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.graph.builder import build_graph
from mpd_assistant.responses.engine import TemplateNotFound, render
from mpd_assistant.routing.intents import Agent, Intent, Mode
from mpd_assistant.routing.modes import escalate_mode
from mpd_assistant.routing.router import detect_language, route


@pytest.mark.parametrize(
    "text,intent",
    [
        ("Hi", Intent.GREETING),
        ("hello!", Intent.GREETING),
        ("I want to hire your team to build a mobile app", Intent.PROJECT_INQUIRY),
        ("How much does a website cost?", Intent.QUOTE_REQUEST),
        ("Can you schedule a call with me next week", Intent.BOOK_MEETING),
        ("I need to speak to a human", Intent.HUMAN_REQUEST),
        ("This is unacceptable, I want a refund", Intent.COMPLAINT),
        ("Send an email to the team", Intent.EMAIL_REQUEST),
        ("What services do you offer?", Intent.FAQ),
    ],
)
def test_routes_common_intents(text, intent):
    assert route(text, verified=True).intent == intent


def test_hi_does_not_match_inside_other_words():
    assert route("history of the high hire").intent != Intent.GREETING


def test_booking_is_not_swallowed_by_faq_template():
    decision = route("book a meeting with your team", verified=True)
    assert decision.intent == Intent.BOOK_MEETING and decision.mode == Mode.REASONED


def test_identity_gate_flag():
    assert route("I want a quote", verified=False).requires_identity
    assert not route("I want a quote", verified=True).requires_identity
    assert not route("what services do you offer", verified=False).requires_identity


def test_language_and_ladder():
    assert detect_language("Bonjour, je voudrais un devis") == "fr"
    assert detect_language("Hello, I need a quote") == "en"
    assert escalate_mode(Mode.TEMPLATED) == Mode.GENERATED
    assert escalate_mode(Mode.ESCALATE) == Mode.ESCALATE


def test_templates_fallback_and_variables():
    assert "Référence" not in render("greeting", "de")  # falls back to English
    assert "ABC" in render("escalation_notice", "fr", {"reference": "ABC"})
    with pytest.raises(TemplateNotFound):
        render("does_not_exist")


async def run(graph, text, verified=False, thread="t1"):
    state = {"messages": [{"role": "user", "content": text}], "session_id": thread, "verified": verified}
    return await graph.ainvoke(state, config={"configurable": {"thread_id": thread}})


async def test_greeting_uses_template_without_llm():
    out = await run(build_graph(), "hello")
    assert out["response"].startswith("Hello!")


async def test_unverified_visitor_is_gated_before_any_agent():
    called = []

    async def quote_agent(state):
        called.append(1)
        return {"response": "quote"}

    out = await run(build_graph({Agent.QUOTE: quote_agent}), "I need a quote", verified=False)
    assert not called and "verify" in out["response"].lower()


async def test_verified_user_reaches_agent():
    async def quote_agent(state):
        return {"response": "here is your quote"}

    out = await run(build_graph({Agent.QUOTE: quote_agent}), "I need a quote", verified=True)
    assert out["response"] == "here is your quote"


async def test_agent_failure_degrades_to_template():
    async def broken(state):
        raise RuntimeError("llm down")

    out = await run(build_graph({Agent.QUOTE: broken}), "I need a quote", verified=True)
    assert "try again" in out["response"].lower()


async def test_human_request_escalates_with_reference():
    out = await run(build_graph(), "let me talk to a human", verified=True)
    assert out["escalated"] and out["reference"] in out["response"]


async def test_checkpointer_keeps_conversation():
    graph = build_graph(checkpointer=MemorySaver())
    await run(graph, "hello", thread="keep")
    state = await graph.aget_state({"configurable": {"thread_id": "keep"}})
    roles = [m["role"] for m in state.values["messages"]]
    assert roles == ["user", "assistant"]


# --- evaluator gate and privacy boundary ---------------------------------------
from mpd_assistant.core import crypto  # noqa: E402
from mpd_assistant.graph.service import ChatService  # noqa: E402
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault  # noqa: E402


def make_service(runners=None):
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    return ChatService(build_graph(runners or {}, checkpointer=MemorySaver()), vault), vault


async def test_bad_agent_output_is_replaced_by_safe_template():
    async def leaky(state):
        return {"response": "TOOL: send_email to everyone"}

    svc, _ = make_service({Agent.QUOTE: leaky})
    result = await svc.chat("s1", "I need a quote", verified=True)
    assert "try again" in result.reply.lower() and "tool_syntax_leak" in result.eval_reasons


async def test_unissued_pii_in_model_output_escalates():
    async def leaky(state):
        return {"response": "Call Bob at (416) 967-1111"}

    svc, _ = make_service({Agent.QUOTE: leaky})
    result = await svc.chat("s1", "I need a quote", verified=True)
    assert result.escalated and "(416)" not in result.reply


async def test_model_sees_tokens_but_user_gets_real_value_back():
    seen = {}

    async def echo(state):
        seen["text"] = state["messages"][-1]["content"]
        return {"response": "I will email you at <EMAIL_1>."}

    svc, vault = make_service({Agent.QUOTE: echo})
    result = await svc.chat("s1", "I need a quote, my email is ann@example.com", verified=True)
    assert "ann@example.com" not in seen["text"] and "<EMAIL_1>" in seen["text"]
    assert "ann@example.com" in result.reply


async def test_checkpoint_never_contains_raw_pii():
    svc, _ = make_service()
    await svc.chat("s2", "hello, I am ann@example.com", verified=True)
    state = await svc._graph.aget_state({"configurable": {"thread_id": "s2"}})
    assert "ann@example.com" not in str(state.values)
