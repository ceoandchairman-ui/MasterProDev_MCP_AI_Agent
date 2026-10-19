"""Production entrypoint: `uvicorn mpd_assistant.api.app:app`. Builds services from environment settings."""

import logging

import httpx
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.agents.factory import build_runners
from mpd_assistant.agents.lead_conversion.agent import MemoryLeadRepository
from mpd_assistant.api.main import Services, create_app
from mpd_assistant.business.catalog import load_catalog
from mpd_assistant.business.escalations import EscalationFlow, EscalationService, InMemoryEscalations
from mpd_assistant.business.escalations_sql import SqlEscalationRepository
from mpd_assistant.business.leads_sql import SqlLeadRepository
from mpd_assistant.cache.semantic import SemanticCache
from mpd_assistant.cache.store import MemoryBackend, RedisBackend, ResponseCache
from mpd_assistant.channels.gateway import ChannelGateway
from mpd_assistant.core.config import get_settings
from mpd_assistant.core.crypto import FieldCipher
from mpd_assistant.core.db import check_engine, ensure_tenant, make_engine
from mpd_assistant.core.kv import KeyValueStore, MemoryKV, RedisKV
from mpd_assistant.core.llm.budget import TokenBudget
from mpd_assistant.core.llm.client import OpenAICompatibleLLM
from mpd_assistant.core.llm.metered import MeteredLLM
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
from mpd_assistant.memory.long_term.sql import SqlMemoryRepository
from mpd_assistant.memory.long_term.store import MemoryStore
from mpd_assistant.memory.pipeline import MemoryWiring
from mpd_assistant.memory.short_term.summary import RollingSummarizer
from mpd_assistant.messaging.confirmations import ConfirmationService
from mpd_assistant.messaging.models import Channel, OutboundMessage, Purpose
from mpd_assistant.messaging.providers import SendGridProvider, TwilioProvider
from mpd_assistant.messaging.service import MessengerSender, NotificationService
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


def _repositories(database_url: str, production: bool):
    """Postgres-backed repositories; in development an unreachable database falls back to process memory."""
    engine = make_engine(database_url)
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


def _notifications(settings, kv: KeyValueStore) -> NotificationService:
    providers = []
    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and (settings.TWILIO_SMS_FROM or settings.TWILIO_WHATSAPP_FROM):
        providers.append(
            TwilioProvider(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_SMS_FROM, settings.TWILIO_WHATSAPP_FROM)
        )
    if settings.SENDGRID_API_KEY and settings.EMAIL_FROM:
        providers.append(SendGridProvider(settings.SENDGRID_API_KEY, settings.EMAIL_FROM))
    return NotificationService(providers, kv, daily_cap_per_channel=settings.MESSAGES_DAILY_CAP)


def build_services() -> Services:
    settings = get_settings()
    settings.require_crypto_keys()
    cipher = FieldCipher(settings.DATA_ENCRYPTION_KEY)  # type: ignore[arg-type]
    prod = settings.is_production

    kv = _kv(settings.REDIS_URL, prod)
    notifications = _notifications(settings, kv)
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

    session_repo, users, leads, engine, tenant = _repositories(settings.DATABASE_URL, prod)
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

    llm = None
    if settings.HUGGINGFACE_API_KEY and settings.HUGGINGFACE_MODEL:
        models = {"mid": settings.HUGGINGFACE_MODEL, "cheap": settings.LLM_MODEL_CHEAP or settings.HUGGINGFACE_MODEL, "reasoning": settings.LLM_MODEL_REASONING or settings.HUGGINGFACE_MODEL}
        llm = GuardedLLM(OpenAICompatibleLLM(settings.LLM_BASE_URL, settings.HUGGINGFACE_API_KEY, models))

    executor = None
    if settings.CALENDAR_SERVER_URL and settings.GMAIL_SERVER_URL and settings.MCP_SERVICE_KEY:
        cal, mail = settings.CALENDAR_SERVER_URL, settings.GMAIL_SERVER_URL
        routes = {
            "get_calendar_events": (cal, "get_events"),
            "create_calendar_event": (cal, "create_event"),
            "delete_calendar_event": (cal, "delete_event"),
            "get_emails": (mail, "get_emails"),
            "read_email": (mail, "read_email"),
            "send_email": (mail, "send_email"),
        }
        backend = http_backend(routes, settings.MCP_SERVICE_KEY, httpx.AsyncClient())
        executor = ToolExecutor(
            registry,
            backend,
            rehydrate=vault.detokenize,
            pseudonymize=vault.tokenize,
            audit_sink=SqlToolAudit(engine) if engine is not None else None,
        )

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
    catalog = load_catalog(settings.CATALOG_PATH) if settings.CATALOG_PATH else None
    budget = TokenBudget(kv, settings.SESSION_DAILY_TOKENS, settings.GLOBAL_DAILY_TOKENS)
    escalation_repo = SqlEscalationRepository(engine) if engine is not None else InMemoryEscalations()
    escalation_flow = EscalationFlow(EscalationService(repo=escalation_repo), notifications, settings.ESCALATION_EMAIL)
    google = None
    if engine is not None:
        google = GoogleOAuth(engine, kv, cipher, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET, settings.GOOGLE_OAUTH_REDIRECT_URI)
    token_provider = google.access_token if google and google.configured else None
    runners = build_runners(llm, retriever, executor, registry, leads=leads, catalog=catalog,
                            on_booked=ConfirmationService(notifications, users, cipher).booking_confirmed,
                            retrieval_min_score=min_score, google_token_provider=token_provider, on_quote_review=escalation_flow.hook, budget=budget)
    graph = build_graph(runners, checkpointer=_checkpointer(settings.REDIS_URL, prod), escalation_hook=escalation_flow.hook,
        judge=LlmJudge(MeteredLLM(llm, "judge", budget), settings.JUDGE_SAMPLE_RATE) if llm is not None and settings.JUDGE_SAMPLE_RATE > 0 else None,
    )
    memory_store = MemoryStore(repo=SqlMemoryRepository(engine) if engine is not None else None)
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
    dsr = DataSubjectService(engine, kv, cipher, settings.BLIND_INDEX_KEY, memory_store) if engine is not None else None  # type: ignore[arg-type]
    response_cache = _response_cache(settings, prod)
    semantic = SemanticCache(response_cache.backend, embedder, settings.SEMANTIC_CACHE_THRESHOLD) if response_cache and embedder and settings.SEMANTIC_CACHE_ENABLED else None
    chat = ChatService(
        graph,
        vault,
        cache=response_cache,
        semantic=semantic,
        cache_settings=CacheSettings(tenant=tenant or "default", prompt_version=settings.PROMPT_VERSION, corpus_version=settings.CORPUS_VERSION),
        memory=MemoryWiring(memory_store, llm, users.memory_consent),
        escalations=escalation_flow,
        summarizer=RollingSummarizer(llm, kv) if llm is not None else None,
        budget=budget,
    )
    sessions = SessionService(session_repo)
    gateway = ChannelGateway(chat, sessions, users, notifications, kv, settings.BLIND_INDEX_KEY)  # type: ignore[arg-type]
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
    )


def create():
    """ASGI factory: `uvicorn --factory mpd_assistant.api.app:create`."""
    assert_production_ready()
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    setup_tracing("mpd-api")
    return create_app(build_services())
