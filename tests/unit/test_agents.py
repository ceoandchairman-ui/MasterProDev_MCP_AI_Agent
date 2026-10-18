import json

import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.agents.common import is_affirmative, is_negative, parse_json_object, parse_plan
from mpd_assistant.agents.factory import build_runners
from mpd_assistant.core import crypto
from mpd_assistant.core.llm.client import FakeLLM, FallbackLLM, LLMError, OpenAICompatibleLLM
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.retrieval.hybrid import Hit
from mpd_assistant.routing.intents import Agent
from mpd_assistant.tools.executor import ToolContext, ToolExecutor
from mpd_assistant.tools.registry import Role, default_registry


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits

    async def search(self, query):
        return self.hits


def make_service(llm, hits=None):
    calls = []

    async def backend(tool, args):
        calls.append((tool, args))
        return {"status": "success", "tool": tool}

    registry = default_registry()
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    executor = ToolExecutor(registry, backend, rehydrate=vault.detokenize, pseudonymize=vault.tokenize)
    runners = build_runners(llm, FakeRetriever(hits or []), executor, registry)
    return ChatService(build_graph(runners, checkpointer=MemorySaver()), vault), calls


# --- helpers ----------------------------------------------------------------
def test_parse_json_from_fenced_prose():
    fenced = 'Sure!\n```json\n{"steps": [{"tool": "a", "args": {}}]}\n```'
    assert parse_json_object(fenced) == {"steps": [{"tool": "a", "args": {}}]}
    assert parse_json_object("no json here") is None
    assert parse_json_object('{"a": {"b": 1}} trailing {') == {"a": {"b": 1}}


def test_plan_drops_unknown_tools_and_caps_steps():
    steps_in = [{"tool": "send_email", "args": {}}, {"tool": "drop_db", "args": {}}, {"tool": "send_email", "args": "bad"}] * 3
    steps = parse_plan(json.dumps({"steps": steps_in}), ["send_email"], max_steps=2)
    assert [s.tool for s in steps] == ["send_email"]


def test_confirmation_words():
    assert is_affirmative("Yes, go ahead!") and is_affirmative("oui") and not is_affirmative("maybe")
    assert is_negative("no thanks") and is_negative("Cancel") and not is_negative("yes")


# --- llm client ---------------------------------------------------------------
async def test_openai_compatible_client_parses_usage_and_hides_key_on_error():
    def handler(request):
        assert request.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = OpenAICompatibleLLM("https://x/v1", "k", {"mid": "m"}, client=client)
    r = await llm.complete([{"role": "user", "content": "q"}])
    assert (r.text, r.tokens_in, r.tokens_out) == ("hi", 5, 2)

    failing = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    bad = OpenAICompatibleLLM("https://x/v1", "SECRETKEY", {"mid": "m"}, client=failing)
    with pytest.raises(LLMError) as exc:
        await bad.complete([{"role": "user", "content": "q"}])
    assert "SECRETKEY" not in str(exc.value)


async def test_fallback_uses_next_provider():
    first, second = FakeLLM([]), FakeLLM(["ok"])
    assert (await FallbackLLM([first, second]).complete([{"role": "user", "content": "q"}])).text == "ok"
    with pytest.raises(LLMError):
        await FallbackLLM([FakeLLM([])]).complete([{"role": "user", "content": "q"}])


# --- concierge ----------------------------------------------------------------
async def test_concierge_answers_with_sources_and_stays_grounded():
    llm = FakeLLM(["We build custom software."])
    svc, _ = make_service(llm, [Hit("1", "MasterProDev builds custom software.", "about.docx", 0.9)])
    out = await svc.chat("s1", "What does your company do?")
    assert out.reply.startswith("We build custom software.") and "about.docx" in out.reply
    prompt = llm.calls[0][1]["content"]
    assert "Context:" in prompt and "custom software" in prompt


async def test_concierge_says_no_answer_without_calling_llm():
    llm = FakeLLM(["should not be used"])
    svc, _ = make_service(llm, [Hit("1", "unrelated", "x.docx", 0.01)])
    out = await svc.chat("s1", "What is the meaning of life?")
    assert "find a reliable answer" in out.reply and llm.calls == []


async def test_concierge_degrades_on_llm_failure():
    svc, _ = make_service(FakeLLM([]), [Hit("1", "text", "a.docx", 0.9)])
    assert "try again" in (await svc.chat("s1", "What do you do?")).reply.lower()


# --- comms with confirmation ------------------------------------------------------
PLAN = json.dumps(
    {"steps": [{"tool": "create_calendar_event", "args": {"title": "Discovery call", "start_time": "2026-11-02T14:00:00", "end_time": "2026-11-02T14:30:00"}}]}
)


async def test_side_effect_waits_for_confirmation_then_runs_once():
    svc, calls = make_service(FakeLLM([PLAN]))
    first = await svc.chat("s1", "Please book a call on Nov 2 at 2pm", verified=True)
    assert "Shall I go ahead" in first.reply and calls == []
    second = await svc.chat("s1", "yes", verified=True)
    assert second.reply.startswith("Done") and len(calls) == 1 and calls[0][0] == "create_calendar_event"


async def test_declining_cancels_and_nothing_runs():
    svc, calls = make_service(FakeLLM([PLAN]))
    await svc.chat("s1", "book a meeting for Nov 2", verified=True)
    out = await svc.chat("s1", "no", verified=True)
    assert "won't" in out.reply and calls == []


async def test_read_tool_runs_without_confirmation_and_unknown_tools_are_dropped():
    plan = json.dumps({"steps": [{"tool": "get_calendar_events", "args": {"days": 3}}, {"tool": "drop_all", "args": {}}]})
    svc, calls = make_service(FakeLLM([plan]))
    out = await svc.chat("s1", "schedule check availability this week", verified=True)
    assert [c[0] for c in calls] == ["get_calendar_events"] and out.reply.startswith("Done")


async def test_unverified_user_never_reaches_comms_agent():
    llm = FakeLLM([PLAN])
    svc, calls = make_service(llm)
    out = await svc.chat("s1", "book a meeting for Nov 2", verified=False)
    assert "verify" in out.reply.lower() and llm.calls == [] and calls == []


# --- executor guard rails -------------------------------------------------------------
async def test_executor_denies_wrong_agent_role_and_untrusted_context():
    async def backend(tool, args):
        return {"ok": True}

    ex = ToolExecutor(default_registry(), backend)
    assert (await ex.run("send_email", {}, ToolContext(Agent.CONCIERGE, Role.STAFF))).status == "denied"
    assert (await ex.run("send_email", {}, ToolContext(Agent.COMMS_SCHEDULING, Role.VISITOR))).status == "denied"
    confirmed = ToolContext(Agent.COMMS_SCHEDULING, Role.VERIFIED, frozenset({"send_email"}), untrusted_content_in_context=True)
    assert (await ex.run("send_email", {}, confirmed)).status == "ok"
    unconfirmed = ToolContext(Agent.COMMS_SCHEDULING, Role.VERIFIED, frozenset(), untrusted_content_in_context=True)
    assert (await ex.run("send_email", {}, unconfirmed)).reason == "side_effect_after_untrusted_content"


async def test_executor_hides_backend_exception_text():
    async def backend(tool, args):
        raise RuntimeError("password=hunter2")

    ex = ToolExecutor(default_registry(), backend)
    outcome = await ex.run("search_knowledge_base", {}, ToolContext(Agent.CONCIERGE, Role.VISITOR))
    assert outcome.status == "error" and "hunter2" not in str(outcome)


async def test_tool_receives_real_values_but_state_and_reply_flow_stays_tokenized():
    plan = json.dumps({"steps": [{"tool": "send_email", "args": {"to": "<EMAIL_1>", "subject": "Hello", "body": "Thanks"}}]})
    seen = {}

    async def backend(tool, args):
        seen.update(args)
        return {"status": "sent", "to": args["to"]}

    llm = FakeLLM([plan])
    registry = default_registry()
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    executor = ToolExecutor(registry, backend, rehydrate=vault.detokenize, pseudonymize=vault.tokenize)
    graph = build_graph(build_runners(llm, FakeRetriever([]), executor, registry), checkpointer=MemorySaver())
    svc = ChatService(graph, vault)

    first = await svc.chat("s9", "send an email to ann@example.com saying thanks", verified=True)
    assert "ann@example.com" in first.reply  # user sees their own value
    assert seen == {}  # nothing sent before confirmation
    done = await svc.chat("s9", "yes", verified=True)
    assert seen["to"] == "ann@example.com"  # the tool got the real address
    assert done.reply.startswith("Done") and "ann@example.com" in done.reply
    state = await graph.aget_state({"configurable": {"thread_id": "s9"}})
    assert "ann@example.com" not in str(state.values)  # checkpoint stays free of raw PII


async def test_http_backend_routes_to_server_tool_name_with_service_key():
    from mpd_assistant.tools.executor import http_backend

    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "success"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    call = http_backend({"create_calendar_event": ("http://cal:8001/", "create_event")}, "svc-key", client)
    assert await call("create_calendar_event", {"title": "x"}) == {"status": "success"}
    assert seen["url"] == "http://cal:8001/call?tool_name=create_event"
    assert seen["auth"] == "Bearer svc-key" and seen["body"] == {"title": "x"}
    with pytest.raises(LookupError):
        await call("unknown", {})
