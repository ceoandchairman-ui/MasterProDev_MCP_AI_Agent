"""Wiring: the application factory fills every front door, tool routes follow configuration, and the chat service
feeds entity, topic, upload and style context to the graph."""

import dataclasses
from types import SimpleNamespace

from fastapi.testclient import TestClient

from mpd_assistant.api import app as app_module
from mpd_assistant.core import config, crypto
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.core.llm.client import LLMResult
from mpd_assistant.graph import service as service_module
from mpd_assistant.graph.service import ChatService
from mpd_assistant.memory.short_term.entities import EntityTracker
from mpd_assistant.memory.short_term.topics import TopicTracker
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.routing.intents import Mode
from mpd_assistant.routing.router import route


def _env(monkeypatch, **extra):
    base = {
        "SECRET_KEY": "x" * 16,
        "DATABASE_URL": "postgresql://u:p@127.0.0.1:1/d",
        "REDIS_URL": "redis://127.0.0.1:1",
        "DATA_ENCRYPTION_KEY": crypto.generate_key(),
        "BLIND_INDEX_KEY": crypto.generate_key(),
        "METRICS_TOKEN": "m",
        "ENV": "development",
    }
    for k, v in {**base, **extra}.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()


# --- factory -----------------------------------------------------------------------------
def test_factory_fills_every_front_door(monkeypatch):
    _env(monkeypatch, ADMIN_TOKEN="staff-secret", CORS_ORIGINS="https://a.example, https://b.example", EMAIL_INBOUND_TOKEN="tok")
    services = app_module.build_services()
    assert services.payments is not None and services.payments.configured is False  # no Stripe keys yet
    assert services.uploads is not None and services.voice is not None and services.email_inbound is not None
    assert services.admin is not None and services.admin_token == "staff-secret" and services.entities is not None
    assert services.cors_origins == ("https://a.example", "https://b.example")
    assert services.trusted_proxy_hops == 1 and services.edge_requests_per_minute == 120
    assert services.speech_to_text is None and services.text_to_speech is None  # no audio endpoint configured
    config.get_settings.cache_clear()


def test_stripe_and_audio_keys_switch_features_on(monkeypatch):
    _env(monkeypatch, STRIPE_SECRET_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET="whsec_x", AUDIO_BASE_URL="https://audio.example/v1", AUDIO_API_KEY="k")
    services = app_module.build_services()
    assert services.payments.configured is True
    assert services.speech_to_text is not None and services.text_to_speech is not None
    config.get_settings.cache_clear()


def test_admin_and_session_end_routes_work_through_the_factory(monkeypatch):
    _env(monkeypatch, ADMIN_TOKEN="staff-secret")
    client = TestClient(app_module.create())
    assert client.get("/v2/admin/overview").status_code == 401
    assert client.get("/v2/admin/overview", headers={"Authorization": "Bearer staff-secret"}).status_code == 200
    sid = client.post("/v2/session").json()["session_id"]
    assert client.post(f"/v2/session/{sid}/end").json() == {"status": "ended"}
    assert client.post("/v2/session/nope/end").status_code == 404
    config.get_settings.cache_clear()


def test_stripe_webhook_is_closed_until_configured(monkeypatch):
    _env(monkeypatch)
    client = TestClient(app_module.create())
    assert client.post("/v2/webhooks/stripe", content=b"{}").status_code == 404
    config.get_settings.cache_clear()


# --- tool routes -------------------------------------------------------------------------
def test_tool_routes_follow_configured_services(monkeypatch):
    _env(monkeypatch)
    assert app_module.tool_routes(config.get_settings()) == {}
    _env(monkeypatch, CALENDAR_SERVER_URL="http://cal", DB_SERVER_URL="http://db")
    routes = app_module.tool_routes(config.get_settings())
    assert routes["find_free_slots"] == ("http://cal", "find_free_slots")
    assert routes["reschedule_calendar_event"] == ("http://cal", "reschedule_event")
    assert routes["get_quote_details"] == ("http://db", "get_quote")
    assert routes["list_my_quotes"] == ("http://db", "list_quotes_for_user")
    assert "send_email" not in routes
    config.get_settings.cache_clear()


def test_every_routed_tool_is_declared_in_the_registry():
    from mpd_assistant.tools.registry import default_registry

    registry = default_registry()
    for table in (app_module.CALENDAR_TOOLS, app_module.GMAIL_TOOLS, app_module.DB_TOOLS):
        for tool in table:
            assert registry.get(tool) is not None, tool


def test_entity_sink_remembers_ids_only():
    entities = EntityTracker(MemoryKV())
    sink = app_module.entity_sink(entities)
    ctx = SimpleNamespace(session_id="t1")
    ok = lambda output: SimpleNamespace(status="ok", output=output)  # noqa: E731
    sink("get_emails", {}, ctx, ok({"emails": [{"id": "m1", "subject": "Private subject"}]}), 1)
    sink("create_calendar_event", {}, ctx, ok({"event": {"id": "ev1", "title": "Secret meeting"}}), 1)
    sink("get_calendar_events", {}, SimpleNamespace(session_id=""), ok({"events": [{"id": "x"}]}), 1)  # no thread: ignored
    sink("read_email", {"email_id": "m2"}, ctx, SimpleNamespace(status="error", output={}), 1)  # failed call: ignored
    stored = {(e.kind, e.ref, e.label) for e in entities.recent("t1")}
    assert stored == {("email", "m1", ""), ("meeting", "ev1", "")}
    assert entities.resolve("t1", "move that meeting")[0].ref == "ev1"


def test_fan_out_survives_a_failing_sink():
    seen = []

    def boom(*args):
        raise RuntimeError("x")

    app_module.fan_out(boom, None, lambda *a: seen.append(a))(1, 2)
    assert seen == [(1, 2)]


# --- chat service hooks ------------------------------------------------------------------
class Graph:
    def __init__(self):
        self.inputs = []

    async def ainvoke(self, state, config=None):
        self.inputs.append(state)
        return {"response": "Here is a helpful answer.", "eval_verdict": "pass", "mode": "reasoned", "intent": "knowledge_question", "agent": "concierge", "language": "en"}


class Patterns:
    def __init__(self):
        self.proposed = []

    def few_shot_block(self, intent, language, limit=2):
        return f"STYLE for {intent}/{language}"

    def propose(self, intent, language, user_text, reply_text):
        self.proposed.append((intent, user_text, reply_text))


class Episodes:
    def __init__(self):
        self.calls = []

    async def record(self, user_id, thread_id, outcome="no_outcome"):
        self.calls.append((user_id, thread_id, outcome))


def make_service(monkeypatch, mode=Mode.REASONED, **hooks):
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    graph = Graph()
    real = service_module.route
    monkeypatch.setattr(service_module, "route", lambda text, verified=False: dataclasses.replace(real(text, verified=verified), mode=mode))
    return ChatService(graph, vault, **hooks), graph


async def test_context_from_entities_uploads_and_patterns_reaches_the_graph(monkeypatch):
    kv = MemoryKV()
    entities, patterns = EntityTracker(kv), Patterns()
    entities.remember("t1", "email", "m123")
    uploads = SimpleNamespace(context_for=lambda thread: "FILE: notes.txt - project brief")
    svc, graph = make_service(monkeypatch, entities=entities, uploads=uploads, patterns=patterns)
    await svc.chat("t1", "please reply to that email", verified=True, user_id="u1")
    seen = graph.inputs[0]
    assert "email m123" in seen["context_notes"]
    assert seen["attachment_context"] == "FILE: notes.txt - project brief"
    assert seen["style_examples"].startswith("STYLE for ")


async def test_topic_changes_are_noted_and_parked_work_can_resume(monkeypatch):
    svc, graph = make_service(monkeypatch, topics=TopicTracker(MemoryKV()))
    await svc.chat("t2", "I want to book a meeting for next week to discuss our website", verified=True, user_id="u1")
    await svc.chat("t2", "What programming languages does your team use?", verified=True, user_id="u1")
    assert "changed topic" in graph.inputs[1]["context_notes"]


async def test_good_reasoned_replies_are_proposed_as_patterns_but_templated_ones_are_not(monkeypatch):
    patterns = Patterns()
    svc, _ = make_service(monkeypatch, patterns=patterns)
    await svc.chat("t3", "Tell me how a custom CRM project usually runs", verified=True, user_id="u1")
    assert len(patterns.proposed) == 1 and patterns.proposed[0][2] == "Here is a helpful answer."
    templated = Patterns()
    svc, _ = make_service(monkeypatch, mode=Mode.TEMPLATED, patterns=templated)
    await svc.chat("t4", "hello there", verified=True, user_id="u1")
    assert templated.proposed == []


async def test_end_conversation_records_an_episode_and_clears_working_state(monkeypatch):
    kv = MemoryKV()
    entities, topics, episodes = EntityTracker(kv), TopicTracker(kv), Episodes()
    entities.remember("t5", "email", "m1")
    topics.observe("t5", "booking", "book a call", task_open=True)
    svc, _ = make_service(monkeypatch, entities=entities, topics=topics, episodes=episodes)
    await svc.end_conversation("t5", "u1", "closed")
    assert episodes.calls == [("u1", "t5", "closed")]
    assert entities.recent("t5") == [] and topics.parked("t5") == []
    await svc.end_conversation("t5", None, "closed")  # a visitor has no episode
    assert len(episodes.calls) == 1


def test_route_is_real_for_the_dataclass_replace_trick():
    assert dataclasses.is_dataclass(route("hello"))
    assert LLMResult("x").text == "x"


# --- OCR engine selection ---------------------------------------------------------------
def test_ocr_engine_follows_settings():
    from mpd_assistant.multimodal.ocr import TesseractOcr, VisionModelOcr, build_ocr

    def cfg(**kw):
        base = {"OCR_ENGINE": "none", "VISION_MODEL": None, "HUGGINGFACE_API_KEY": None, "LLM_BASE_URL": "https://llm.example/v1"}
        return SimpleNamespace(**{**base, **kw})

    assert build_ocr(cfg()) is None
    assert isinstance(build_ocr(cfg(OCR_ENGINE="tesseract")), TesseractOcr)
    assert build_ocr(cfg(OCR_ENGINE="vision")) is None  # vision needs a model and a key
    assert isinstance(build_ocr(cfg(OCR_ENGINE="vision", VISION_MODEL="m", HUGGINGFACE_API_KEY="k")), VisionModelOcr)


def test_worker_reindex_job_receives_the_ocr_engine(monkeypatch):
    import inspect

    from mpd_assistant.worker import main as worker

    assert "ocr=build_ocr(s)" in inspect.getsource(worker.build_jobs)
