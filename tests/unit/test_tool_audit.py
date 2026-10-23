from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.pool import StaticPool

from mpd_assistant.core.db import ensure_tenant
from mpd_assistant.core.models import Base, ToolCall
from mpd_assistant.core.models import Session as SessionRow
from mpd_assistant.routing.intents import Agent
from mpd_assistant.tools.audit_sql import SqlToolAudit
from mpd_assistant.tools.executor import ToolContext, ToolExecutor
from mpd_assistant.tools.registry import Role, default_registry


def setup():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    tenant = ensure_tenant(engine)
    with DbSession(engine) as db:
        db.add(SessionRow(id="row1", thread_id="t1", tenant_id=tenant))
        db.commit()
    return engine


async def test_every_call_is_recorded_with_redacted_arguments():
    engine = setup()

    async def backend(tool, args):
        return {"status": "success", "items": [1]}

    ex = ToolExecutor(default_registry(), backend, audit_sink=SqlToolAudit(engine))
    ctx = ToolContext(Agent.COMMS_SCHEDULING, Role.VERIFIED, frozenset({"send_email"}), session_id="t1", session_row="row1")
    await ex.run("send_email", {"to": "ann@example.com", "body": "call (416) 967-1111", "subject": "hi"}, ctx)
    await ex.run("send_email", {"to": "x"}, ToolContext(Agent.COMMS_SCHEDULING, Role.VERIFIED, frozenset(), session_id="t1", session_row="row1"))
    with DbSession(engine) as db:
        rows = list(db.scalars(select(ToolCall).order_by(ToolCall.created_at)))
    assert [r.status for r in rows] == ["ok", "needs_confirmation"]
    stored = str(rows[0].input_redacted)
    assert "ann@example.com" not in stored and "967-1111" not in stored and rows[0].tool == "send_email"


async def test_calls_without_a_session_row_and_sink_failures_do_not_break_the_tool():
    engine = setup()

    async def backend(tool, args):
        return {"ok": True}

    ex = ToolExecutor(default_registry(), backend, audit_sink=SqlToolAudit(engine))
    out = await ex.run("search_knowledge_base", {"query": "x"}, ToolContext(Agent.CONCIERGE, Role.VISITOR))
    assert out.status == "ok"

    def boom(*args):
        raise RuntimeError("db down")

    ex2 = ToolExecutor(default_registry(), backend, audit_sink=boom)
    assert (await ex2.run("search_knowledge_base", {}, ToolContext(Agent.CONCIERGE, Role.VISITOR))).status == "ok"


async def test_in_memory_audit_is_bounded():
    async def backend(tool, args):
        return {}

    ex = ToolExecutor(default_registry(), backend)
    for _ in range(600):
        await ex.run("search_knowledge_base", {}, ToolContext(Agent.CONCIERGE, Role.VISITOR))
    assert len(ex.audit) == 500
