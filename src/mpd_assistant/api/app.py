"""Production entrypoint: `uvicorn mpd_assistant.api.app:app`. Builds services from environment settings."""

import logging

import httpx
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.agents.factory import build_runners
from mpd_assistant.agents.lead_conversion.agent import MemoryLeadRepository
from mpd_assistant.api.main import Services, create_app
from mpd_assistant.business.catalog import load_catalog
from mpd_assistant.channels.gateway import ChannelGateway
from mpd_assistant.core.config import get_settings
from mpd_assistant.core.crypto import FieldCipher
from mpd_assistant.core.kv import KeyValueStore, MemoryKV, RedisKV
from mpd_assistant.core.llm.client import OpenAICompatibleLLM
from mpd_assistant.core.logging import configure_logging
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.senders import ConsoleSender, UnconfiguredSender
from mpd_assistant.identity.service import IdentityService, MemoryUserRepository
from mpd_assistant.messaging.confirmations import ConfirmationService
from mpd_assistant.messaging.models import Channel
from mpd_assistant.messaging.providers import SendGridProvider, TwilioProvider
from mpd_assistant.messaging.service import MessengerSender, NotificationService
from mpd_assistant.observability.otel import setup_tracing
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.sessions.service import MemorySessionRepository, SessionService
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

    users = MemoryUserRepository()  # replaced by the SQL repository when the database wave lands
    identity = IdentityService(
        cipher,
        settings.BLIND_INDEX_KEY,  # type: ignore[arg-type]
        users,
        OtpService(settings.SECRET_KEY + ":email"),
        OtpService(settings.SECRET_KEY + ":sms"),
        email_sender,
        sms_sender,
    )
    vault = PiiVault(cipher, MemoryVaultStore())
    registry = default_registry()

    llm = None
    if settings.HUGGINGFACE_API_KEY and settings.HUGGINGFACE_MODEL:
        models = {"mid": settings.HUGGINGFACE_MODEL, "cheap": settings.LLM_MODEL_CHEAP or settings.HUGGINGFACE_MODEL, "reasoning": settings.LLM_MODEL_REASONING or settings.HUGGINGFACE_MODEL}
        llm = OpenAICompatibleLLM(settings.LLM_BASE_URL, settings.HUGGINGFACE_API_KEY, models)

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

    # The retriever (Weaviate hybrid search) is wired in the retrieval wave; until then the concierge is not registered.
    catalog = load_catalog(settings.CATALOG_PATH) if settings.CATALOG_PATH else None
    runners = build_runners(llm, None, executor, registry, leads=MemoryLeadRepository(), catalog=catalog,
                            on_booked=ConfirmationService(notifications, users, cipher).booking_confirmed)
    graph = build_graph(runners, checkpointer=_checkpointer(settings.REDIS_URL, prod))
    chat = ChatService(graph, vault)
    sessions = SessionService(MemorySessionRepository())
    gateway = ChannelGateway(chat, sessions, users, notifications, kv, settings.BLIND_INDEX_KEY)  # type: ignore[arg-type]
    return Services(
        chat=chat,
        sessions=sessions,
        identity=identity,
        metrics_token=settings.METRICS_TOKEN,
        gateway=gateway,
        twilio_auth_token=settings.TWILIO_AUTH_TOKEN,
        public_url=settings.PUBLIC_DOMAIN,
    )


def create():
    """ASGI factory: `uvicorn --factory mpd_assistant.api.app:create`."""
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    setup_tracing("mpd-api")
    return create_app(build_services())
