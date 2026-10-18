import json

from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.agents.factory import build_runners
from mpd_assistant.agents.lead_conversion.agent import MemoryLeadRepository
from mpd_assistant.agents.solution_architect.agent import Scope, render_scope
from mpd_assistant.business.quoting import CatalogItem
from mpd_assistant.core import crypto
from mpd_assistant.core.llm.client import FakeLLM
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.tools.registry import default_registry

CATALOG = {"dev-hour": CatalogItem("dev-hour", "Development hour", "hour", 15000)}

SCOPE = {
    "summary": "A booking mobile app for a logistics firm.",
    "milestones": [{"name": "Discovery", "weeks": 2, "deliverables": ["requirements", "wireframes"]}, {"name": "Build", "weeks": 10, "deliverables": ["app"]}],
    "assumptions": ["Existing API"],
    "risks": ["Scope creep"],
}


def make_service(llm, leads=None):
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    runners = build_runners(llm, None, None, default_registry(), leads=leads or MemoryLeadRepository(), catalog=CATALOG)
    return ChatService(build_graph(runners, checkpointer=MemorySaver()), vault)


# --- lead conversion ----------------------------------------------------------------
async def test_lead_collects_slots_one_question_at_a_time_then_offers_call():
    leads = MemoryLeadRepository()
    llm = FakeLLM(
        [
            json.dumps({"need": "a mobile booking app", "timeline": None, "budget": None}),
            json.dumps({"need": None, "timeline": "by March", "budget": None}),
            json.dumps({"need": None, "timeline": None, "budget": "around 40k"}),
        ]
    )
    svc = make_service(llm, leads)
    r1 = await svc.chat("s1", "I want to build a mobile booking app", verified=True, user_id="u1")
    assert "When would you like" in r1.reply and leads.rows["u1"]["stage"] == "engaged"
    r2 = await svc.chat("s1", "I want to build it by March", verified=True, user_id="u1")
    assert "budget" in r2.reply.lower()
    r3 = await svc.chat("s1", "I want to build it, budget is around 40k", verified=True, user_id="u1")
    assert "discovery call" in r3.reply.lower() and leads.rows["u1"]["stage"] == "qualified"
    assert set(leads.rows["u1"]["slots"]) == {"need", "timeline", "budget"}


async def test_lead_ignores_model_garbage_and_keeps_asking():
    svc = make_service(FakeLLM(["I think the user wants stuff"]))
    out = await svc.chat("s1", "I want to build something", verified=True, user_id="u1")
    assert "what would you like to build" in out.reply.lower()


async def test_lead_stage_cannot_be_set_by_the_model():
    leads = MemoryLeadRepository()
    svc = make_service(FakeLLM([json.dumps({"need": "x", "stage": "won"})]), leads)
    await svc.chat("s1", "I want to build an app", verified=True, user_id="u1")
    assert leads.rows["u1"]["stage"] == "engaged"


# --- architect ------------------------------------------------------------------------
async def test_architect_returns_validated_scope_rendered_by_code():
    llm = FakeLLM([json.dumps(SCOPE)])
    svc = make_service(llm)
    out = await svc.chat("s1", "Please draft the technical scope and roadmap", verified=True, user_id="u1")
    assert "1. Discovery (~2 wk)" in out.reply and "Risks: Scope creep" in out.reply


async def test_architect_retries_once_on_invalid_schema_then_gives_up():
    llm = FakeLLM(["not json", json.dumps({"summary": "x", "milestones": []})])
    svc = make_service(llm)
    out = await svc.chat("s1", "draft the scope for my project", verified=True, user_id="u1")
    assert len(llm.calls) == 2 and "reliable answer" in out.reply


def test_scope_schema_bounds():
    for bad in ({"summary": "", "milestones": []}, {**SCOPE, "milestones": [{"name": "x", "weeks": 99, "deliverables": ["a"]}]}):
        try:
            Scope.model_validate(bad)
        except Exception:
            continue
        raise AssertionError("expected validation error")
    assert "Discovery" in render_scope(Scope.model_validate(SCOPE))


# --- quote ------------------------------------------------------------------------------
async def test_quote_requires_scope_first():
    svc = make_service(FakeLLM([]))
    out = await svc.chat("s1", "How much would it cost?", verified=True, user_id="u1")
    assert "project scope" in out.reply


async def test_quote_amounts_come_from_code_not_the_model():
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    llm = FakeLLM([json.dumps({"selections": [{"sku": "dev-hour", "quantity": 40, "price": 1}]})])
    runners = build_runners(llm, None, None, default_registry(), leads=MemoryLeadRepository(), catalog=CATALOG)
    graph = build_graph(runners, checkpointer=MemorySaver())
    await graph.aupdate_state({"configurable": {"thread_id": "q1"}}, {"scope": SCOPE, "verified": True, "messages": []})
    svc = ChatService(graph, vault)
    out = await svc.chat("q1", "how much will this cost", verified=True, user_id="u1")
    assert "$6,000.00 CAD" in out.reply and "Total: $6,780.00 CAD" in out.reply


async def test_large_quote_goes_to_human_review_without_showing_numbers():
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    llm = FakeLLM([json.dumps({"selections": [{"sku": "dev-hour", "quantity": 500}]})])
    runners = build_runners(llm, None, None, default_registry(), catalog=CATALOG)
    graph = build_graph(runners, checkpointer=MemorySaver())
    await graph.aupdate_state({"configurable": {"thread_id": "q2"}}, {"scope": SCOPE, "messages": []})
    out = await ChatService(graph, vault).chat("q2", "how much will this cost", verified=True, user_id="u1")
    assert "review the numbers" in out.reply and "$" not in out.reply


async def test_unknown_sku_from_model_is_rejected():
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    llm = FakeLLM([json.dumps({"selections": [{"sku": "free-everything", "quantity": 1}]})])
    runners = build_runners(llm, None, None, default_registry(), catalog=CATALOG)
    graph = build_graph(runners, checkpointer=MemorySaver())
    await graph.aupdate_state({"configurable": {"thread_id": "q3"}}, {"scope": SCOPE, "messages": []})
    out = await ChatService(graph, vault).chat("q3", "how much will this cost", verified=True, user_id="u1")
    assert "$" not in out.reply and "couldn't build a reliable quote" in out.reply
