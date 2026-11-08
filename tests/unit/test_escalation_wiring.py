import json

from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.pool import StaticPool

from mpd_assistant.agents.factory import build_runners
from mpd_assistant.business.escalations import EscalationFlow, EscalationService, InMemoryEscalations
from mpd_assistant.business.escalations_sql import SqlEscalationRepository
from mpd_assistant.business.quoting import CatalogItem
from mpd_assistant.core import crypto
from mpd_assistant.core.db import ensure_tenant
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.llm.client import FakeLLM
from mpd_assistant.core.models import Base
from mpd_assistant.core.models import Session as SessionRow
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.messaging.models import Channel, SendResult
from mpd_assistant.messaging.service import NotificationService
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.tools.registry import default_registry


class Mailbox:
    channels = frozenset({Channel.EMAIL})

    def __init__(self):
        self.sent = []

    async def send(self, channel, to, body, subject=None):
        self.sent.append((to, subject, body))
        return SendResult("sent", provider_id="m")


def build(repo=None, staff="team@example.com", llm=None, catalog=None):
    mailbox = Mailbox()
    notifications = NotificationService([mailbox], MemoryKV())
    flow = EscalationFlow(EscalationService(repo=repo or InMemoryEscalations()), notifications, staff)
    registry = default_registry()
    runners = build_runners(llm, None, None, registry, catalog=catalog, on_quote_review=flow.hook) if llm else {}
    graph = build_graph(runners, checkpointer=MemorySaver(), escalation_hook=flow.hook)
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    return ChatService(graph, vault, escalations=flow), flow, mailbox


async def test_human_request_creates_one_record_alerts_staff_and_pauses_the_bot():
    svc, flow, mailbox = build()
    first = await svc.chat("t1", "I want to talk to a real person", verified=True, session_row="row1")
    assert first.escalated and first.reference and first.reference in first.reply
    assert len(mailbox.sent) == 1 and mailbox.sent[0][0] == "team@example.com"
    assert first.reference in mailbox.sent[0][2] and "user:" in mailbox.sent[0][2]

    second = await svc.chat("t1", "hello? anyone there", verified=True, session_row="row1")
    assert second.reference == first.reference and "notified" in second.reply and len(mailbox.sent) == 1
    assert second.agent == "escalation"


async def test_resolving_the_escalation_resumes_the_assistant():
    svc, flow, _ = build()
    first = await svc.chat("t1", "I need a human", verified=True, session_row="row1")
    assert flow._service.resolve(first.reference)
    again = await svc.chat("t1", "hello", verified=True, session_row="row1")
    assert again.reply.startswith("Hello") and not flow.is_paused("row1")


async def test_alert_failure_never_blocks_the_handover_message():
    class Down:
        channels = frozenset({Channel.EMAIL})

        async def send(self, *a, **k):
            raise RuntimeError("smtp down")

    flow = EscalationFlow(EscalationService(), NotificationService([Down()], MemoryKV()), "team@example.com")
    graph = build_graph({}, checkpointer=MemorySaver(), escalation_hook=flow.hook)
    svc = ChatService(graph, PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore()), escalations=flow)
    out = await svc.chat("t1", "get me a human", verified=True, session_row="row1")
    assert out.escalated and "Reference" in out.reply and flow.is_paused("row1")


async def test_large_quote_review_raises_an_escalation_with_a_reference():
    plan = json.dumps({"selections": [{"sku": "dev-hour", "quantity": 500}]})
    catalog = {"dev-hour": CatalogItem("dev-hour", "Development hour", "hour", 15000)}
    svc, flow, mailbox = build(llm=FakeLLM([plan]), catalog=catalog)
    await svc._graph.aupdate_state({"configurable": {"thread_id": "q1"}}, {"scope": {"summary": "x"}, "messages": []})
    out = await svc.chat("q1", "how much will this cost", verified=True, user_id="u1", session_row="row-q")
    assert "review the numbers" in out.reply and "$" not in out.reply
    assert flow.is_paused("row-q") and len(mailbox.sent) == 1 and "quote_review" in mailbox.sent[0][2]


def test_staff_summary_masks_personal_data():
    svc = EscalationService()
    esc = svc.raise_escalation("s1", "human_request", [{"role": "user", "content": "call me on (416) 967-1111 or ann@example.com"}])
    assert "967-1111" not in esc.summary and "ann@example.com" not in esc.summary


def test_sql_repository_pauses_across_instances_and_resolves():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    tenant = ensure_tenant(engine)
    with DbSession(engine) as db:
        db.add(SessionRow(id="s1", thread_id="t1", tenant_id=tenant))
        db.commit()
    a, b = EscalationService(repo=SqlEscalationRepository(engine)), EscalationService(repo=SqlEscalationRepository(engine))
    esc = a.raise_escalation("s1", "human_request", [])
    assert b.is_paused("s1") and b.open_reference("s1") == esc.reference
    assert a.raise_escalation("s1", "complaint", []).reference == esc.reference
    assert b.resolve(esc.reference) and not a.is_paused("s1")
