"""Production entrypoint: `uvicorn mpd_assistant.api.app:app`. Builds services from environment settings."""

import logging

import httpx
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.agents.factory import build_runners
from mpd_assistant.agents.lead_conversion.agent import MemoryLeadRepository
from mpd_assistant.agents.prompts import prompt_set_version
from mpd_assistant.api.main import Services, create_app
from mpd_assistant.business.admin import AdminService, SqlAuditLog
from mpd_assistant.business.catalog import load_catalog
from mpd_assistant.business.companies import MemoryCompanyRepository, SqlCompanyRepository
from mpd_assistant.business.escalations import EscalationFlow, EscalationService, InMemoryEscalations
from mpd_assistant.business.escalations_sql import SqlEscalationRepository
from mpd_assistant.business.leads_sql import SqlLeadRepository
from mpd_assistant.business.payments import PaymentService, StripeCheckout
from mpd_assistant.business.people import PeopleDirectory
from mpd_assistant.business.quote_review import QuoteReview
from mpd_assistant.business.quote_store import MemoryQuoteRepository, SqlQuoteRepository
from mpd_assistant.cache.semantic import SemanticCache
from mpd_assistant.cache.store import MemoryBackend, RedisBackend, ResponseCache
from mpd_assistant.channels.email_inbound import EmailGateway
from mpd_assistant.channels.gateway import ChannelGateway
from mpd_assistant.channels.voice import VoiceGateway
from mpd_assistant.core.config import get_settings
from mpd_assistant.core.crypto import FieldCipher
from mpd_assistant.core.db import check_engine, ensure_tenant, make_engine
from mpd_assistant.core.kv import KeyValueStore, MemoryKV, RedisKV
from mpd_assistant.core.llm.budget import TokenBudget
from mpd_assistant.core.llm.client import OpenAICompatibleLLM
from mpd_assistant.core.llm.metered import MeteredLLM
from mpd_assistant.core.llm.resilient import BreakerLLM
from mpd_assistant.core.logging import configure_logging
from mpd_assistant.core.startup import assert_production_ready
from mpd_assistant.evaluation.online.judge import LlmJudge
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import CacheSettings, ChatService
from mpd_assistant.identity.abuse import SmsAbuseGuard
from mpd_assistant.identity.account import AccountService
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.senders import ConsoleSender, UnconfiguredSender
from mpd_assistant.identity.service import IdentityService, MemoryUserRepository
from mpd_assistant.identity.sql import SqlUserRepository
from mpd_assistant.integrations.google_oauth import GoogleOAuth
from mpd_assistant.memory.episodic import EpisodeWriter
from mpd_assistant.memory.long_term.sql import SqlMemoryRepository
from mpd_assistant.memory.long_term.store import MemoryStore
from mpd_assistant.memory.pipeline import MemoryWiring
from mpd_assistant.memory.procedural import PatternLibrary, SqlPatternRepository
from mpd_assistant.memory.short_term.entities import EntityTracker
from mpd_assistant.memory.short_term.summary import RollingSummarizer
from mpd_assistant.memory.short_term.topics import TopicTracker
from mpd_assistant.memory.tools import MemoryTools, with_memory_tools
from mpd_assistant.messaging.confirmations import ConfirmationService
from mpd_assistant.messaging.delivery import DeliveryTracker
from mpd_assistant.messaging.models import Channel, OutboundMessage, Purpose
from mpd_assistant.messaging.providers import SendGridProvider, TwilioProvider
from mpd_assistant.messaging.service import MessengerSender, NotificationService
from mpd_assistant.multimodal.ocr import build_ocr
from mpd_assistant.multimodal.uploads import UploadService
from mpd_assistant.multimodal.voice import OpenAICompatibleSTT, OpenAICompatibleTTS
from mpd_assistant.observability.otel import setup_tracing
from mpd_assistant.privacy.boundaries import GuardedLLM
from mpd_assistant.privacy.dsr import DataSubjectService
from mpd_assistant.privacy.kv_store import KvVaultStore
from mpd_assistant.privacy.vault import PiiVault
from mpd_assistant.retrieval.embeddings import OpenAICompatibleEmbedder
from mpd_assistant.retrieval.pg import PgRetriever
from mpd_assistant.retrieval.rerank import HostedReranker
from mpd_assistant.sessions.service import MemorySessionRepository, SessionService
from mpd_assistant.sessions.sql import SqlSessionRepository
from mpd_assistant.sessions.turns import SqlTurnRecorder
from mpd_assistant.tools.audit_sql import SqlToolAudit
from mpd_assistant.tools.executor import ToolExecutor, http_backend
from mpd_assistant.tools.registry import default_registry

logger = logging.getLogger(__name__)

# Registry tool name -> (server setting, tool name on that server)
CALENDAR_TOOLS = {
    "get_calendar_events": "get_events",
    "find_free_slots": "find_free_slots",
    "create_calendar_event": "create_event",
    "reschedule_calendar_event": "reschedule_event",
    "delete_calendar_event": "delete_event",
}
GMAIL_TOOLS = {
    "get_emails": "get_emails",
    "read_email": "read_email",
    "create_email_draft": "create_draft",
    "send_email": "send_email",
}
DB_TOOLS = {
    "get_lead_stage": "get_lead_stage",
    "list_my_quotes": "list_quotes_for_user",
    "get_quote_details": "get_quote",
    "get_customer_profile": "get_customer_profile",
}


def _checkpointer(redis_url: str, production: bool):
    """Redis (Redis Stack) in production; process memory only for local development."""
    try:
        from langgraph.checkpoint.redis import RedisSaver

        saver = RedisSaver.from_conn_string(redis_url)
        saver.setup()
        return saver
    except Exception:
        if production:
            raise
        logger.warning("Redis checkpointer unavailable; using in-memory checkpoints (development only)")
        return MemorySaver()


def _kv(redis_url: str, production: bool) -> KeyValueStore:
    try:
        import redis

        client = redis.Redis.from_url(redis_url)
        client.ping()
        return RedisKV(client)
    except Exception:
        if production:
            raise
        logger.warning("Redis unavailable; using in-memory key-value store (development only)")
        return MemoryKV()


def _repositories(database_url: str, production: bool, pool_size: int = 5, max_overflow: int = 5):
    """Postgres-backed repositories; in development an unreachable database falls back to process memory."""
    engine = make_engine(database_url, pool_size, max_overflow)
    if check_engine(engine):
        tenant = ensure_tenant(engine)
        return SqlSessionRepository(engine, tenant), SqlUserRepository(engine, tenant), SqlLeadRepository(engine, tenant), engine, tenant
    if production:
        raise RuntimeError("Database is unreachable")
    logger.warning("Database unavailable; using in-memory repositories (development only)")
    return MemorySessionRepository(), MemoryUserRepository(), MemoryLeadRepository(), None, None


def _response_cache(settings, production: bool):
    if not settings.CACHE_ENABLED:
        return None
    try:
        import redis.asyncio as aioredis

        return ResponseCache(RedisBackend(aioredis.Redis.from_url(settings.REDIS_CACHE_URL or settings.REDIS_URL)))
    except Exception:
        if production:
            raise
        return ResponseCache(MemoryBackend())


def _notifications(settings, kv: KeyValueStore, tracker=None) -> NotificationService:
    providers = []
    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and (settings.TWILIO_SMS_FROM or settings.TWILIO_WHATSAPP_FROM):
        providers.append(
            TwilioProvider(
                settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_SMS_FROM, settings.TWILIO_WHATSAPP_FROM,
                status_callback_url=settings.PUBLIC_DOMAIN.rstrip("/") + "/v2/channels/twilio/status",
            )
        )
    if settings.SENDGRID_API_KEY and settings.EMAIL_FROM:
        providers.append(SendGridProvider(settings.SENDGRID_API_KEY, settings.EMAIL_FROM))
    return NotificationService(providers, kv, daily_cap_per_channel=settings.MESSAGES_DAILY_CAP, tracker=tracker)


def tool_routes(settings) -> dict:
    """Which registry tools have a server behind them: a tool is only routable when its service URL is configured."""
    routes = {}
    for url, tools in ((settings.CALENDAR_SERVER_URL, CALENDAR_TOOLS), (settings.GMAIL_SERVER_URL, GMAIL_TOOLS), (settings.DB_SERVER_URL, DB_TOOLS)):
        if url:
            routes.update({tool: (url, server_tool) for tool, server_tool in tools.items()})
    return routes


def entity_sink(entities: EntityTracker):
    """Remembers which emails, meetings and files a tool call touched, so 'that email' or 'the meeting' can be resolved later.
    Only opaque ids are stored, never subjects, titles or addresses."""

    def sink(tool, args, ctx, outcome, latency_ms) -> None:
        if outcome.status != "ok" or not ctx.session_id:
            return
        out = outcome.output or {}
        thread = ctx.session_id
        if tool == "get_emails":
            for mail in (out.get("emails") or [])[:3]:
                if mail.get("id"):
                    entities.remember(thread, "email", str(mail["id"]))
        elif tool == "read_email" and args.get("email_id"):
            entities.remember(thread, "email", str(args["email_id"]))
        elif tool == "get_calendar_events":
            for event in (out.get("events") or [])[:3]:
                if event.get("id"):
                    entities.remember(thread, "meeting", str(event["id"]))
        elif tool in ("create_calendar_event", "reschedule_calendar_event"):
            event = out.get("event") or {}
            if event.get("id"):
                entities.remember(thread, "meeting", str(event["id"]))

    return sink


def fan_out(*sinks):
    """Calls every sink; one failing never stops the others (the executor already guards the whole group)."""

    def run(*args) -> None:
        for sink in sinks:
            if sink is None:
                continue
            try:
                sink(*args)
            except Exception:
                logger.exception("tool sink failed")

    return run


async def _no_remote_servers(tool, args):
    raise LookupError("no server for tool")


def build_services() -> Services:
    settings = get_settings()
    settings.require_crypto_keys()
    cipher = FieldCipher(*settings.cipher_keys())
    prod = settings.is_production

    kv = _kv(settings.REDIS_URL, prod)
    delivery = DeliveryTracker(kv)
    notifications = _notifications(settings, kv, delivery)
    can_email = notifications.has_channel(Channel.EMAIL)
    can_sms = notifications.has_channel(Channel.SMS)
    if can_email:
        email_sender = MessengerSender(notifications, Channel.EMAIL)
    else:
        email_sender = UnconfiguredSender("email") if prod else ConsoleSender("email")
    if can_sms:
        sms_sender = MessengerSender(notifications, Channel.SMS)
    else:
        sms_sender = UnconfiguredSender("sms") if prod else ConsoleSender("sms")

    session_repo, users, leads, engine, tenant = _repositories(settings.DATABASE_URL, prod, settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW)
    identity = IdentityService(
        cipher,
        settings.BLIND_INDEX_KEY,  # type: ignore[arg-type]
        users,
        OtpService(settings.SECRET_KEY + ":email", store=kv, namespace="otp-email"),
        OtpService(settings.SECRET_KEY + ":sms", store=kv, namespace="otp-sms"),
        email_sender,
        sms_sender,
        kv=kv,
        abuse=SmsAbuseGuard(kv, countries=settings.SMS_ALLOWED_COUNTRIES.split(",")),
    )
    vault = PiiVault(cipher, KvVaultStore(kv))
    registry = default_registry()

    async def tell_old_contact(kind: str, old_value: str) -> None:
        channel = Channel.EMAIL if kind == "email" else Channel.SMS
        if notifications.has_channel(channel):
            await notifications.send(OutboundMessage(channel, old_value, "contact_changed", "en", {}, Purpose.TRANSACTIONAL))

    account = AccountService(
        users,
        cipher,
        settings.BLIND_INDEX_KEY,  # type: ignore[arg-type]
        kv,
        OtpService(settings.SECRET_KEY + ":stepup", store=kv, namespace="otp-stepup"),
        OtpService(settings.SECRET_KEY + ":email", store=kv, namespace="otp-email"),
        OtpService(settings.SECRET_KEY + ":sms", store=kv, namespace="otp-sms"),
        email_sender,
        sms_sender,
        notify_change=tell_old_contact,
    )

    llm = None
    if settings.HUGGINGFACE_API_KEY and settings.HUGGINGFACE_MODEL:
        models = {"mid": settings.HUGGINGFACE_MODEL, "cheap": settings.LLM_MODEL_CHEAP or settings.HUGGINGFACE_MODEL, "reasoning": settings.LLM_MODEL_REASONING or settings.HUGGINGFACE_MODEL}
        llm = GuardedLLM(BreakerLLM(OpenAICompatibleLLM(settings.LLM_BASE_URL, settings.HUGGINGFACE_API_KEY, models)))

    retriever = None
    embedder = None
    min_score = settings.RETRIEVAL_MIN_SCORE
    embedding_key = settings.EMBEDDING_API_KEY or settings.HUGGINGFACE_API_KEY
    if embedding_key:
        embedder = OpenAICompatibleEmbedder(settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL, embedding_key, settings.EMBEDDING_MODEL)
    if engine is not None and embedder is not None:
        reranker = HostedReranker(settings.RERANK_BASE_URL, settings.RERANK_API_KEY, settings.RERANK_MODEL) if settings.RERANK_BASE_URL and settings.RERANK_API_KEY else None
        retriever = PgRetriever(engine, tenant, embedder, reranker=reranker)
        min_score = settings.RERANK_MIN_SCORE if reranker else settings.RETRIEVAL_MIN_SCORE

    # Memory, trackers and learned patterns
    memory_store = MemoryStore(repo=SqlMemoryRepository(engine) if engine is not None else None)
    entities = EntityTracker(kv)
    topics = TopicTracker(kv)
    patterns = PatternLibrary(SqlPatternRepository(engine, tenant) if engine is not None else None)
    summarizer = RollingSummarizer(llm, kv) if llm is not None else None
    episodes = EpisodeWriter(memory_store, summarizer, users.memory_consent, kv, llm) if summarizer is not None else None

    # Tools: remote servers plus the local memory tools, behind one guarded executor
    executor = None
    routes = tool_routes(settings)
    if routes and settings.MCP_SERVICE_KEY:
        remote = http_backend(routes, settings.MCP_SERVICE_KEY, httpx.AsyncClient())
        backend = with_memory_tools(MemoryTools(memory_store, users.memory_consent, kv, embedder), remote)
        executor = ToolExecutor(
            registry,
            backend,
            rehydrate=vault.detokenize,
            pseudonymize=vault.tokenize,
            audit_sink=fan_out(SqlToolAudit(engine) if engine is not None else None, entity_sink(entities)),
            kv=kv,
        )

    catalog = load_catalog(settings.CATALOG_PATH) if settings.CATALOG_PATH else None
    budget = TokenBudget(kv, settings.SESSION_DAILY_TOKENS, settings.GLOBAL_DAILY_TOKENS)
    escalation_repo = SqlEscalationRepository(engine) if engine is not None else InMemoryEscalations()
    escalation_service = EscalationService(repo=escalation_repo)
    escalation_flow = EscalationFlow(escalation_service, notifications, settings.ESCALATION_EMAIL)
    google = None
    if engine is not None:
        google = GoogleOAuth(engine, kv, cipher, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET, settings.GOOGLE_OAUTH_REDIRECT_URI)
    token_provider = google.access_token if google and google.configured else None

    # Revenue: stored quotes are the source of truth; the signed webhook is the only path to "paid"
    quotes = SqlQuoteRepository(engine, tenant) if engine is not None else MemoryQuoteRepository()
    confirmations = ConfirmationService(notifications, users, cipher)
    return_url = (settings.PAYMENT_RETURN_URL or settings.PUBLIC_DOMAIN).rstrip("/")

    async def receipt(quote) -> None:
        await confirmations.payment_received(quote.user_id, quote.ref)

    async def mismatch(quote) -> None:
        logger.error("payment amount mismatch for quote %s; not marked paid", quote.ref)

    checkout = StripeCheckout(settings.STRIPE_SECRET_KEY, f"{return_url}/?payment=success", f"{return_url}/?payment=cancelled") if settings.STRIPE_SECRET_KEY else None
    payments = PaymentService(quotes, checkout, kv, settings.STRIPE_WEBHOOK_SECRET, on_paid=receipt, on_mismatch=mismatch)

    runners = build_runners(
        llm, retriever, executor, registry, leads=leads, catalog=catalog,
        on_booked=confirmations.booking_confirmed,
        retrieval_min_score=min_score, google_token_provider=token_provider, on_quote_review=escalation_flow.hook, budget=budget,
        quotes=quotes, payments=payments, has_step_up=account.has_recent, start_step_up=account.stepup_start,
        companies=SqlCompanyRepository(engine, tenant) if engine is not None else MemoryCompanyRepository(),
    )
    graph = build_graph(runners, checkpointer=_checkpointer(settings.REDIS_URL, prod), escalation_hook=escalation_flow.hook,
        judge=LlmJudge(MeteredLLM(llm, "judge", budget), settings.JUDGE_SAMPLE_RATE) if llm is not None and settings.JUDGE_SAMPLE_RATE > 0 else None,
    )

    dsr = DataSubjectService(engine, kv, cipher, settings.BLIND_INDEX_KEY, memory_store) if engine is not None else None  # type: ignore[arg-type]
    response_cache = _response_cache(settings, prod)
    semantic = SemanticCache(response_cache.backend, embedder, settings.SEMANTIC_CACHE_THRESHOLD) if response_cache and embedder and settings.SEMANTIC_CACHE_ENABLED else None

    # Files, voice and the other front doors
    uploads = UploadService(kv, vault, build_ocr(settings))
    audio_ready = bool(settings.AUDIO_BASE_URL and settings.AUDIO_API_KEY)
    speech_to_text = OpenAICompatibleSTT(settings.AUDIO_BASE_URL, settings.AUDIO_API_KEY, settings.STT_MODEL) if audio_ready else None  # type: ignore[arg-type]
    text_to_speech = OpenAICompatibleTTS(settings.AUDIO_BASE_URL, settings.AUDIO_API_KEY, settings.TTS_MODEL) if audio_ready else None  # type: ignore[arg-type]

    chat = ChatService(
        graph,
        vault,
        cache=response_cache,
        semantic=semantic,
        cache_settings=CacheSettings(tenant=tenant or "default", prompt_version=f"{settings.PROMPT_VERSION}.{prompt_set_version()}", corpus_version=settings.CORPUS_VERSION),
        memory=MemoryWiring(memory_store, llm, users.memory_consent),
        escalations=escalation_flow,
        summarizer=summarizer,
        budget=budget,
        entities=entities,
        topics=topics,
        uploads=uploads,
        patterns=patterns,
        episodes=episodes,
    )
    sessions = SessionService(session_repo)
    gateway = ChannelGateway(chat, sessions, users, notifications, kv, settings.BLIND_INDEX_KEY)  # type: ignore[arg-type]
    voice = VoiceGateway(gateway, kv, settings.PUBLIC_DOMAIN.rstrip("/") + "/v2/channels/voice")
    email_inbound = EmailGateway(chat, sessions, users, notifications, kv, settings.BLIND_INDEX_KEY, settings.EMAIL_FROM)  # type: ignore[arg-type]

    purgers = {}
    if response_cache is not None:
        purgers["response"] = response_cache.invalidate
    if semantic is not None:
        purgers["semantic"] = semantic.invalidate
    audit = SqlAuditLog(engine) if engine is not None else None
    people = PeopleDirectory(engine, tenant, cipher, settings.BLIND_INDEX_KEY, audit) if engine is not None else None  # type: ignore[arg-type]
    admin = AdminService(
        escalation_service,
        escalation_repo,
        audit=audit,
        grafana_url=settings.GRAFANA_URL,
        langsmith_url=settings.LANGSMITH_URL,
        patterns=patterns,
        cache_purgers=purgers,
        people=people,
        delivery=delivery,
        quotes=QuoteReview(quotes, audit, on_decision=lambda quote, approved: confirmations.quote_decided(quote.user_id, quote.ref, approved)),
    )
    return Services(
        chat=chat,
        sessions=sessions,
        identity=identity,
        metrics_token=settings.METRICS_TOKEN,
        gateway=gateway,
        twilio_auth_token=settings.TWILIO_AUTH_TOKEN,
        public_url=settings.PUBLIC_DOMAIN,
        google=google,
        kv=kv,
        turns=SqlTurnRecorder(engine) if engine is not None else None,
        users=users,
        memory_store=memory_store,
        account=account,
        dsr=dsr,
        payments=payments,
        uploads=uploads,
        speech_to_text=speech_to_text,
        text_to_speech=text_to_speech,
        voice=voice,
        email_inbound=email_inbound,
        email_inbound_token=settings.EMAIL_INBOUND_TOKEN,
        admin=admin,
        admin_token=settings.ADMIN_TOKEN,
        entities=entities,
        delivery=delivery,
        cors_origins=tuple(o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()),
        trusted_proxy_hops=settings.TRUSTED_PROXY_HOPS,
        edge_requests_per_minute=settings.EDGE_REQUESTS_PER_MINUTE,
    )


def create():
    """ASGI factory: `uvicorn --factory mpd_assistant.api.app:create`."""
    assert_production_ready()
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    setup_tracing("mpd-api")
    return create_app(build_services())
