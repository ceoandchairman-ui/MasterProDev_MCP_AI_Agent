"""Tool schemas: argument validation, user-id injection, idempotency keys, planner catalogue, company data queries."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.agents.common import PlanStep
from mpd_assistant.business.companies import MemoryCompanyRepository, SqlCompanyRepository, clean_name, name_key
from mpd_assistant.core.models import Base, Company, Lead, Quote, Tenant, User
from mpd_assistant.routing.intents import Agent
from mpd_assistant.tools.executor import ToolContext, ToolExecutor
from mpd_assistant.tools.registry import Role, default_registry
from services.mcp_db.main import DatabaseMCPServer

REG = default_registry()


# --- validation -------------------------------------------------------------------------
def test_valid_event_passes_and_unknown_keys_are_reported():
    ok = {"title": "Call", "start_time": "2026-11-02T14:00:00", "end_time": "2026-11-02T14:30:00", "attendees": ["ann@example.com"]}
    assert REG.validate_args("create_calendar_event", ok) == []
    problems = REG.validate_args("create_calendar_event", {**ok, "drop_table": "x"})
    assert problems == ["drop_table is not an argument of create_calendar_event"]


def test_missing_and_malformed_arguments_are_named():
    problems = REG.validate_args("create_calendar_event", {"title": "Call", "start_time": "next tuesday"})
    assert "end_time is required" in problems and any(p.startswith("start_time must be an ISO 8601") for p in problems)
    assert REG.validate_args("send_email", {"to": ["nope"], "subject": "s", "body": "b"}) == ["to contains an invalid address"]
    assert REG.validate_args("get_calendar_events", {"days": "3"}) == ["days must be a whole number"]
    assert REG.validate_args("get_calendar_events", {"days": True}) == ["days must be a whole number"]
    assert REG.validate_args("nope", {}) == ["unknown tool"]
    assert REG.validate_args("get_calendar_events", ["x"]) == ["arguments must be an object"]


def test_privacy_tokens_count_as_addresses():
    assert REG.validate_args("send_email", {"to": ["<EMAIL_1>"], "subject": "Hi", "body": "Thanks"}) == []
    assert REG.validate_args("send_email", {"to": "<EMAIL_1>", "subject": "Hi", "body": "Thanks"}) == []  # a single address as plain text
    assert REG.validate_args("send_email", {"to": "a@example.com, b@example.com", "subject": "Hi", "body": "x"}) == []
    assert REG.validate_args("send_email", {"to": [], "subject": "Hi", "body": "x"}) == ["to must be one or more email addresses"]


def test_executor_supplied_arguments_are_not_model_arguments():
    args = {"to": ["a@example.com"], "subject": "s", "body": "b", "idempotency_key": "model-chose-this"}
    assert REG.validate_args("send_email", args) == []  # tolerated here, removed below
    assert "idempotency_key" not in REG.clean_args("send_email", args)
    assert REG.clean_args("get_lead_stage", {"user_id": "someone-else"}) == {}
    assert REG.clean_args("send_email", {"to": ["a@example.com"], "evil": 1}) == {"to": ["a@example.com"]}


def test_planner_catalogue_lists_arguments_and_confirmation():
    text = REG.describe(Agent.COMMS_SCHEDULING, Role.VERIFIED)
    assert "create_calendar_event(title: str, start_time: datetime, end_time: datetime, time_zone?: str" in text
    assert "send_email(" in text and "idempotency_key" not in text
    assert "[needs user confirmation]" in text
    assert "delete_calendar_event" not in text  # staff only
    assert "get_emails" not in text


def test_new_tools_have_the_expected_owners_and_roles():
    assert REG.is_allowed("find_free_slots", Role.VERIFIED, Agent.COMMS_SCHEDULING)
    assert REG.is_allowed("reschedule_calendar_event", Role.VERIFIED, Agent.COMMS_SCHEDULING)
    assert not REG.is_allowed("find_free_slots", Role.VISITOR, Agent.COMMS_SCHEDULING)
    assert REG.get("reschedule_calendar_event").needs_confirmation and REG.get("create_email_draft").needs_confirmation
    assert not REG.is_allowed("get_customer_profile", Role.VERIFIED, Agent.CONCIERGE)
    assert REG.is_allowed("list_my_quotes", Role.VERIFIED, Agent.QUOTE)


# --- executor injection ------------------------------------------------------------------
async def test_user_id_comes_from_the_session_never_from_the_model():
    seen = []

    async def backend(tool, args):
        seen.append((tool, dict(args)))
        return {"rows": []}

    ex = ToolExecutor(REG, backend)
    ctx = ToolContext(Agent.LEAD_CONVERSION, Role.VERIFIED, user_id="a" * 32)
    out = await ex.run("get_lead_stage", {"user_id": "b" * 32}, ctx)  # the model tries another person's id
    assert out.status == "ok" and seen[0][1] == {"user_id": "a" * 32}
    anonymous = await ex.run("get_lead_stage", {}, ToolContext(Agent.LEAD_CONVERSION, Role.VERIFIED))
    assert anonymous.status == "denied" and anonymous.reason == "identity_required" and len(seen) == 1


async def test_write_tools_get_a_stable_idempotency_key():
    seen = []

    async def backend(tool, args):
        seen.append(dict(args))
        return {"status": "success"}

    ex = ToolExecutor(REG, backend)
    ctx = ToolContext(Agent.COMMS_SCHEDULING, Role.VERIFIED, frozenset({"send_email"}), session_id="s1")
    args = {"to": ["a@example.com"], "subject": "Hi", "body": "Thanks"}
    await ex.run("send_email", args, ctx)
    await ex.run("send_email", {**args, "subject": "Different"}, ctx)
    assert seen[0]["idempotency_key"].startswith("s1:") and seen[0]["idempotency_key"] != seen[1]["idempotency_key"]


# --- the Comms agent refuses a plan with bad arguments ------------------------------------
async def test_comms_asks_instead_of_running_an_invalid_plan():
    from mpd_assistant.agents.comms_scheduling.agent import make_comms

    calls = []

    async def backend(tool, args):
        calls.append(tool)
        return {"status": "success"}

    class Planner:
        def __init__(self, plan):
            self.plan, self.prompt = plan, ""

        async def complete(self, messages, **kw):
            self.prompt = messages[0]["content"]
            return type("R", (), {"text": json.dumps(self.plan), "usage": None})()

    bad = Planner({"steps": [{"tool": "create_calendar_event", "args": {"title": "Call"}}]})
    run = make_comms(bad, ToolExecutor(REG, backend), REG)
    out = await run({"messages": [{"role": "user", "content": "book a call"}], "language": "en", "session_id": "s1"})
    assert calls == [] and "end_time is required" in out["response"] and out["pending_action"] is None
    assert "create_calendar_event(title: str" in bad.prompt  # the planner was shown the argument names

    good = Planner({"steps": [{"tool": "get_calendar_events", "args": {"days": 3, "bogus": 1}}]})
    run = make_comms(good, ToolExecutor(REG, backend), REG)
    out = await run({"messages": [{"role": "user", "content": "what is on?"}], "language": "en", "session_id": "s1"})
    assert calls == [] and "bogus is not an argument" in out["response"]


# --- company data ------------------------------------------------------------------------
def test_company_names_are_normalised():
    assert name_key("  Acme   Corp ") == "acme corp" and clean_name("A") is None and clean_name(5) is None
    repo = MemoryCompanyRepository()
    repo.link_user("u1", " Acme  Corp ")
    assert repo.by_user["u1"] == "Acme Corp"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_SERVICE_KEY", "svc")
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}")
    Base.metadata.create_all(engine)
    ids = {}
    with DbSession(engine) as s:
        tenant = Tenant(name="masterprodev")
        s.add(tenant)
        s.flush()
        for label in ("ann", "bob"):
            user = User(tenant_id=tenant.id, name_enc="n", email_enc="e", email_index=label, phone_enc="p", phone_index=label)
            s.add(user)
            s.flush()
            lead = Lead(tenant_id=tenant.id, user_id=user.id, stage="qualified", timeline="Q1", budget_range="10-20k")
            s.add(lead)
            s.flush()
            s.add(Quote(lead_id=lead.id, line_items=[{"sku": "web", "quantity": "1", "total_cents": 500000}], total_cents=500000, currency="CAD", content_hash="h",
                        status="approved", expires_at=datetime.now(UTC) + timedelta(days=5)))
            ids[label] = (tenant.id, user.id)
        s.commit()
    SqlCompanyRepository(engine, ids["ann"][0]).link_user(ids["ann"][1], "Acme Corp")
    SqlCompanyRepository(engine, ids["ann"][0]).link_user(ids["bob"][1], "acme   corp")  # same company, different spelling
    return TestClient(DatabaseMCPServer(engine).app), engine, ids


def call(client, tool, params):
    return client.post("/call", params={"tool_name": tool}, json=params, headers={"Authorization": "Bearer svc"}).json()


def test_customer_profile_has_company_but_no_personal_data(db):
    client, engine, ids = db
    row = call(client, "get_customer_profile", {"user_id": ids["ann"][1]})["rows"][0]
    assert row["company"] == "Acme Corp" and row["stage"] == "qualified" and row["quote_count"] == 1
    assert not {"name", "email", "phone", "name_enc", "email_enc"} & set(row)
    with DbSession(engine) as s:
        assert s.query(Company).count() == 1  # both spellings resolved to one company


def test_quote_lookup_is_scoped_to_the_user_and_validates_the_reference(db):
    client, engine, ids = db
    with DbSession(engine) as s:
        ref = s.query(Quote).first().id[:8].upper()
        owner = s.query(Lead).filter(Lead.id == s.query(Quote).first().lead_id).first().user_id
    other = ids["bob"][1] if owner == ids["ann"][1] else ids["ann"][1]
    mine = call(client, "get_quote", {"user_id": owner, "quote_ref": ref})["rows"]
    assert mine and mine[0]["total_cents"] == 500000 and mine[0]["line_items"][0]["sku"] == "web"
    assert call(client, "get_quote", {"user_id": other, "quote_ref": ref})["rows"] == []  # someone else's quote is invisible
    assert call(client, "get_quote", {"user_id": owner, "quote_ref": "x; DROP"})["error"] == "invalid_quote_ref"
    assert call(client, "get_customer_profile", {"user_id": "short"})["error"] == "invalid_user_id"
    tools = {t["name"] for t in client.post("/tools", headers={"Authorization": "Bearer svc"}).json()["tools"]}
    assert {"get_quote", "get_customer_profile", "get_lead_stage", "list_quotes_for_user"} <= tools


def test_plan_step_is_a_plain_value():
    assert PlanStep("t", {}) == PlanStep("t", {})
