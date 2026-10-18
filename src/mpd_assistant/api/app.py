"""Production entrypoint: `uvicorn mpd_assistant.api.app:app`. Builds services from environment settings."""

import logging

import httpx
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.agents.factory import build_runners
from mpd_assistant.agents.lead_conversion.agent import MemoryLeadRepository
from mpd_assistant.api.main import Services, create_app
from mpd_assistant.business.catalog import load_catalog
from mpd_assistant.business.leads_sql import SqlLeadRepository
from mpd_assistant.cache.store import MemoryBackend, RedisBackend, ResponseCache
from mpd_assistant.channels.gateway import ChannelGateway
from mpd_assistant.core.config import get_settings
from mpd_assistant.core.crypto import FieldCipher
from mpd_assistant.core.db import check_engine, ensure_tenant, make_engine
from mpd_assistant.core.kv import KeyValueStore, MemoryKV, RedisKV
from mpd_assistant.core.llm.client import OpenAICompatibleLLM
from mpd_assistant.core.logging import configure_logging
from mpd_assistant.core.startup import assert_production_ready
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import CacheSettings, ChatService
from mpd_assistant.identity.abuse import SmsAbuseGuard
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.senders import ConsoleSender, UnconfiguredSender
from mpd_assistant.identity.service import IdentityService, MemoryUserRepository
from mpd_assistant.identity.sql import SqlUserRepository
from mpd_assistant.integrations.google_oauth import GoogleOAuth
from mpd_assistant.messaging.confirmations import ConfirmationService
from mpd_assistant.messaging.models import Channel
from mpd_assistant.messaging.providers import SendGridProvider, TwilioProvider
from mpd_assistant.messaging.service import MessengerSender, NotificationService
from mpd_assistant.observability.otel import setup_tracing
from mpd_assistant.privacy.boundaries import GuardedLLM
from mpd_assistant.privacy.kv_store import KvVaultStore
from mpd_assistant.privacy.vault import PiiVault
from mpd_assistant.retrieval.embeddings import OpenAICompatibleEmbedder
from mpd_assistant.retrieval.pg import PgRetriever
from mpd_assistant.sessions.service import MemorySessionRepository, SessionService
from mpd_assistant.sessions.sql import SqlSessionRepository
from mpd_assistant.sessions.turns import SqlTurnRecorder
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
        executor = ToolExecutor(registry, backend, rehydrate=vault.detokenize, pseudonymize=vault.tokenize)

    retriever = None
    embedding_key = settings.EMBEDDING_API_KEY or settings.HUGGINGFACE_API_KEY
    if engine is not None and embedding_key:
        embedder = OpenAICompatibleEmbedder(settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL, embedding_key, settings.EMBEDDING_MODEL)
        retriever = PgRetriever(engine, tenant, embedder)
    catalog = load_catalog(settings.CATALOG_PATH) if settings.CATALOG_PATH else None
    google = None
    if engine is not None:
        google = GoogleOAuth(engine, kv, cipher, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET, settings.GOOGLE_OAUTH_REDIRECT_URI)
    token_provider = google.access_token if google and google.configured else None
    runners = build_runners(llm, retriever, executor, registry, leads=leads, catalog=catalog,
                            on_booked=ConfirmationService(notifications, users, cipher).booking_confirmed,
                            retrieval_min_score=settings.RETRIEVAL_MIN_SCORE, google_token_provider=token_provider)
    graph = build_graph(runners, checkpointer=_checkpointer(settings.REDIS_URL, prod))
    chat = ChatService(
        graph,
        vault,
        cache=_response_cache(settings, prod),
        cache_settings=CacheSettings(tenant=tenant or "default", prompt_version=settings.PROMPT_VERSION, corpus_version=settings.CORPUS_VERSION),
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
    )


def create():
    """ASGI factory: `uvicorn --factory mpd_assistant.api.app:create`."""
    assert_production_ready()
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    setup_tracing("mpd-api")
    return create_app(build_services())
