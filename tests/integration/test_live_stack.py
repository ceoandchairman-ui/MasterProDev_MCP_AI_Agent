"""Tests that need the real stores: Postgres with pgvector and Redis Stack (deploy/compose.dev.yml).

    python scripts/dev_env.py
    docker compose -f deploy/compose.dev.yml up -d --wait
    pytest tests/integration/test_live_stack.py -m live -v

They skip themselves when the services are not reachable. Each module run gets its own throwaway database, so nothing
here touches data you keep. Override the addresses with INTEGRATION_DATABASE_URL and INTEGRATION_REDIS_URL.
"""

import hashlib
import hmac
import json
import operator
import os
import random
import time
import uuid
from pathlib import Path
from typing import Annotated, TypedDict

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from mpd_assistant.core import config, crypto

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]
PG_URL = os.environ.get("INTEGRATION_DATABASE_URL", "postgresql://mpd:mpd@127.0.0.1:5433/mpd")
REDIS_URL = os.environ.get("INTEGRATION_REDIS_URL", "redis://127.0.0.1:6380/0")
DIM = 1024  # the document_chunks.embedding column is vector(1024)


# --- the stack ---------------------------------------------------------------------------
def _postgres_up() -> bool:
    try:
        import psycopg2

        psycopg2.connect(PG_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


def _redis_up() -> bool:
    try:
        import redis

        return bool(redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2).ping())
    except Exception:
        return False


@pytest.fixture(scope="module")
def stack():
    if not (_postgres_up() and _redis_up()):
        pytest.skip("Postgres and Redis Stack are not reachable; run: docker compose -f deploy/compose.dev.yml up -d --wait")


def _new_database():
    import psycopg2

    name = "mpd_it_" + uuid.uuid4().hex[:10]
    admin = psycopg2.connect(PG_URL)
    admin.autocommit = True
    admin.cursor().execute(f'CREATE DATABASE "{name}"')
    admin.close()
    return name, make_url(PG_URL).set(database=name).render_as_string(hide_password=False)


def _drop_database(name: str) -> None:
    import psycopg2

    admin = psycopg2.connect(PG_URL)
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
    cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    admin.close()


def migrate(url: str, revision: str = "head", direction: str = "upgrade") -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url  # migrations/env.py reads it
    try:
        getattr(command, direction)(cfg, revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture(scope="module")
def database(stack):
    name, url = _new_database()
    migrate(url)
    yield url
    _drop_database(name)


# --- migrations on real Postgres ---------------------------------------------------------
def test_migrations_apply_roll_back_and_reapply():
    if not (_postgres_up() and _redis_up()):
        pytest.skip("stack not running")
    name, url = _new_database()
    try:
        migrate(url)
        engine = create_engine(url)
        tables = set(inspect(engine).get_table_names())
        assert {"users", "sessions", "turns", "leads", "quotes", "companies", "document_chunks", "memories", "response_patterns"} <= tables
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first()
            index = conn.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_document_chunks_embedding'")).scalar()
        assert index and "hnsw" in index.lower()  # the vector index really is HNSW on cosine distance
        engine.dispose()
        migrate(url, "base", "downgrade")
        engine = create_engine(url)
        assert not ({"users", "companies", "document_chunks"} & set(inspect(engine).get_table_names()))
        engine.dispose()
        migrate(url)  # and forward again
        assert "users" in inspect(create_engine(url)).get_table_names()
    finally:
        _drop_database(name)


# --- vector search -----------------------------------------------------------------------
DOCS = {
    "services.txt": "MasterProDev builds custom mobile apps and web platforms for logistics and retail companies.\n\nWe also provide architecture audits, cloud migration and ongoing maintenance.",
    "contact.txt": "Our Toronto office is open Monday to Friday. You can book a discovery call through the assistant.\n\nPricing depends on scope and is quoted after a short discovery conversation.",
    "equipe.txt": "Notre équipe développe des applications mobiles et des plateformes web sur mesure.",
}


async def test_hybrid_search_runs_on_real_pgvector(database):
    from mpd_assistant.core.db import ensure_tenant, make_engine
    from mpd_assistant.ingestion.indexer import index_document
    from mpd_assistant.retrieval.embeddings import HashEmbedder
    from mpd_assistant.retrieval.pg import PgRetriever

    engine = make_engine(database)
    tenant = ensure_tenant(engine)
    embedder = HashEmbedder(DIM)
    for name, body in DOCS.items():
        await index_document(engine, tenant, name, body, embedder, expected_dim=DIM)
    with engine.connect() as conn:
        first_count = conn.execute(text("SELECT count(*) FROM document_chunks")).scalar()
    for name, body in DOCS.items():  # indexing the same documents again must not duplicate anything
        await index_document(engine, tenant, name, body, embedder, expected_dim=DIM)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM document_chunks")).scalar() == first_count

    retriever = PgRetriever(engine, tenant, embedder)
    hits = await retriever.search("Which custom mobile apps do you build?")
    assert hits and hits[0].source == "services.txt"
    assert (await retriever.search("applications mobiles sur mesure"))[0].source == "equipe.txt"
    assert (await retriever.search("when can I book a discovery call"))[0].source == "contact.txt"


# --- Redis Stack and the checkpointer ----------------------------------------------------
def test_redis_stack_has_the_modules_the_checkpointer_needs(stack):
    import redis

    modules = {str(m.get(b"name", m.get("name", b""))).strip("b'\"").lower() for m in redis.Redis.from_url(REDIS_URL).module_list()}
    assert "search" in modules and "rejson" in modules, modules


class Counter(TypedDict):
    items: Annotated[list, operator.add]


def _graph(saver):
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(Counter)
    builder.add_node("add", lambda state: {"items": [f"turn-{len(state['items']) + 1}"]})
    builder.add_edge(START, "add")
    builder.add_edge("add", END)
    return builder.compile(checkpointer=saver)


def test_redis_checkpoints_survive_a_process_restart(stack):
    from langgraph.checkpoint.redis import RedisSaver

    thread = {"configurable": {"thread_id": "it-" + uuid.uuid4().hex}}
    first = RedisSaver.from_conn_string(REDIS_URL)
    first.setup()
    assert _graph(first).invoke({"items": []}, thread)["items"] == ["turn-1"]
    second = RedisSaver.from_conn_string(REDIS_URL)  # a fresh saver and graph, as after a redeploy
    second.setup()
    assert _graph(second).invoke({"items": []}, thread)["items"] == ["turn-1", "turn-2"]


# --- a whole conversation through the real factory on real stores ------------------------
@pytest.fixture
def live_app(database, monkeypatch):
    """The production factory, pointed at the throwaway database and Redis, with OTP codes captured instead of logged."""
    from mpd_assistant.api import app as app_module
    from mpd_assistant.api.main import create_app
    from mpd_assistant.identity.senders import ConsoleSender

    for key, value in {
        "ENV": "development", "SECRET_KEY": "integration-" + uuid.uuid4().hex, "DATABASE_URL": database, "REDIS_URL": REDIS_URL,
        "DATA_ENCRYPTION_KEY": crypto.generate_key(), "BLIND_INDEX_KEY": crypto.generate_key(), "METRICS_TOKEN": "metrics",
        "ADMIN_TOKEN": "staff-token",
    }.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    codes: dict[str, str] = {}
    monkeypatch.setattr(ConsoleSender, "send", lambda self, target, code: codes.__setitem__(self._channel, code))
    services = app_module.build_services()
    yield TestClient(create_app(services)), services, codes, database
    config.get_settings.cache_clear()


def test_factory_uses_real_stores_not_the_development_fallbacks(live_app):
    _, services, _, _ = live_app
    assert type(services.kv).__name__ == "RedisKV"
    assert "Redis" in type(services.chat._graph.checkpointer).__name__
    assert services.dsr is not None and services.turns is not None  # only built when Postgres answered


def test_signup_chat_account_export_and_erasure(live_app):
    client, services, codes, url = live_app
    email = f"it-{uuid.uuid4().hex[:8]}@example.org"
    phone = f"+1416967{random.randint(1000, 9999)}"

    sid = client.post("/v2/session").json()["session_id"]
    assert client.post("/v2/chat", json={"message": "hi", "session_id": sid}).json()["reply"]

    assert client.post("/v2/identity/start", json={"session_id": sid, "name": "Test Person", "email": email, "phone": phone}).status_code == 202
    verify = client.post("/v2/identity/verify", json={"session_id": sid, "email_code": codes["email"], "phone_code": codes["sms"]})
    assert verify.status_code == 200, verify.text
    assert client.get(f"/v2/session/{sid}").json()["verified"] is True

    reply = client.post("/v2/chat", json={"message": "hello again", "session_id": sid}).json()
    assert reply["reply"]

    engine = create_engine(url)
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT email_enc, name_enc FROM users")).first()
        assert stored and email not in stored[0] and "Test Person" not in stored[1]  # encrypted at rest
        assert conn.execute(text("SELECT count(*) FROM turns")).scalar() >= 2  # turns persisted (pseudonymized)
        rows = " ".join(str(r) for r in conn.execute(text("SELECT * FROM turns")))
        assert email not in rows and phone not in rows

    assert client.post("/v2/memory/consent", json={"session_id": sid, "enabled": True}).json() == {"memory": "on"}
    assert client.get("/v2/memory", params={"session_id": sid}).json() == {"memories": []}
    assert client.get("/v2/account/export", params={"session_id": sid}).status_code == 403  # needs the security code first

    assert client.post("/v2/account/stepup/start", json={"session_id": sid}).status_code == 202
    assert client.post("/v2/account/stepup/verify", json={"session_id": sid, "code": codes["email"]}).status_code == 200
    exported = client.get("/v2/account/export", params={"session_id": sid})
    assert exported.status_code == 200 and exported.json()

    assert client.post(f"/v2/session/{sid}/end").json() == {"status": "ended"}
    assert client.post("/v2/account/delete", json={"session_id": sid, "confirm": "DELETE"}).json()["status"] in ("deleted", "partial")
    assert client.get(f"/v2/session/{sid}").status_code == 404
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users WHERE deleted_at IS NULL")).scalar() == 0


def test_staff_console_and_admin_routes_on_the_live_app(live_app):
    client, *_ = live_app
    assert client.get("/admin").status_code == 200
    auth = {"Authorization": "Bearer staff-token"}
    overview = client.get("/v2/admin/overview", headers=auth).json()
    assert overview["open_escalations"] == 0 and overview["quotes_awaiting_review"] == 0
    assert client.get("/v2/admin/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401


# --- company data service and payments against Postgres ----------------------------------
def _seed_user(engine, tenant):
    from sqlalchemy.orm import Session as DbSession

    from mpd_assistant.core.models import User

    with DbSession(engine) as db:
        user = User(tenant_id=tenant, name_enc="n", email_enc="e", email_index=uuid.uuid4().hex, phone_enc="p", phone_index=uuid.uuid4().hex)
        db.add(user)
        db.commit()
        return user.id


def test_company_data_service_queries_run_on_postgres(database, monkeypatch):
    from mpd_assistant.business.companies import SqlCompanyRepository
    from mpd_assistant.business.quote_store import SqlQuoteRepository
    from mpd_assistant.business.quoting import CatalogItem, build_quote
    from mpd_assistant.core.db import ensure_tenant, make_engine
    from services.mcp_db.main import DatabaseMCPServer

    monkeypatch.setenv("MCP_SERVICE_KEY", "svc")
    engine = make_engine(database)
    tenant = ensure_tenant(engine)
    user = _seed_user(engine, tenant)
    SqlCompanyRepository(engine, tenant).link_user(user, "Acme Corp")
    stored = SqlQuoteRepository(engine, tenant).save(user, build_quote({"dev": CatalogItem("dev", "Development hour", "hour", 15000)}, [{"sku": "dev", "quantity": 10}]))

    client = TestClient(DatabaseMCPServer(engine).app)
    headers = {"Authorization": "Bearer svc"}

    def call(tool, params):
        return client.post("/call", params={"tool_name": tool}, json=params, headers=headers).json()

    profile = call("get_customer_profile", {"user_id": user})["rows"][0]
    assert profile["company"] == "Acme Corp" and profile["quote_count"] == 1
    quote = call("get_quote", {"user_id": user, "quote_ref": stored.ref})["rows"][0]
    assert quote["total_cents"] == stored.total_cents and quote["line_items"][0]["sku"] == "dev"  # JSON column arrives parsed
    assert call("get_quote", {"user_id": uuid.uuid4().hex, "quote_ref": stored.ref})["rows"] == []  # another user sees nothing
    assert call("list_quotes_for_user", {"user_id": user})["rows"][0]["ref"] == stored.ref


async def test_payment_webhook_marks_quotes_paid_in_postgres(database):
    from mpd_assistant.business.payments import CheckoutSession, PaymentService
    from mpd_assistant.business.quote_store import SqlQuoteRepository
    from mpd_assistant.business.quoting import CatalogItem, build_quote
    from mpd_assistant.core.db import ensure_tenant, make_engine
    from mpd_assistant.core.kv import MemoryKV

    engine = make_engine(database)
    tenant = ensure_tenant(engine)
    user = _seed_user(engine, tenant)
    quotes = SqlQuoteRepository(engine, tenant)
    catalog = {"dev": CatalogItem("dev", "Development hour", "hour", 15000)}

    class Provider:
        async def create_session(self, **kw):
            return CheckoutSession("cs_1", "https://pay.example/cs_1")

    secret = "whsec_integration"
    payments = PaymentService(quotes, Provider(), MemoryKV(), secret)

    def signed(event: dict) -> tuple[bytes, str]:
        payload = json.dumps(event).encode()
        stamp = str(int(time.time()))
        digest = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
        return payload, f"t={stamp},v1={digest}"

    def paid_event(event_id, quote, amount):
        return {"id": event_id, "type": "checkout.session.completed",
                "data": {"object": {"payment_status": "paid", "client_reference_id": quote.id, "amount_total": amount, "currency": "cad"}}}

    good = quotes.save(user, build_quote(catalog, [{"sku": "dev", "quantity": 10}]))
    started = await payments.start_checkout(user, good.ref)
    assert started.ok and started.url and quotes.get(good.id).status == "accepted"
    assert (await payments.handle_webhook(*signed(paid_event("evt_1", good, good.total_cents)))).status == "paid"
    assert quotes.get(good.id).status == "paid"
    assert (await payments.handle_webhook(*signed(paid_event("evt_1", good, good.total_cents)))).status == "duplicate"  # Stripe retries are harmless

    wrong = quotes.save(user, build_quote(catalog, [{"sku": "dev", "quantity": 20}]))
    assert (await payments.handle_webhook(*signed(paid_event("evt_2", wrong, wrong.total_cents - 1)))).status == "mismatch"
    assert quotes.get(wrong.id).status == "payment_review"  # a wrong amount is held for a person, never marked paid
