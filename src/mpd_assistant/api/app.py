"""Production entrypoint: `uvicorn mpd_assistant.api.app:app`. Builds services from environment settings."""

import logging

from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.api.main import Services, create_app
from mpd_assistant.core.config import get_settings
from mpd_assistant.core.crypto import FieldCipher
from mpd_assistant.core.logging import configure_logging
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.senders import ConsoleSender, UnconfiguredSender
from mpd_assistant.identity.service import IdentityService, MemoryUserRepository
from mpd_assistant.observability.otel import setup_tracing
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.sessions.service import MemorySessionRepository, SessionService

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


def build_services() -> Services:
    settings = get_settings()
    settings.require_crypto_keys()
    cipher = FieldCipher(settings.DATA_ENCRYPTION_KEY)  # type: ignore[arg-type]
    prod = settings.is_production

    if prod:
        email_sender, sms_sender = UnconfiguredSender("email"), UnconfiguredSender("sms")
    else:
        email_sender, sms_sender = ConsoleSender("email"), ConsoleSender("sms")

    identity = IdentityService(
        cipher,
        settings.BLIND_INDEX_KEY,  # type: ignore[arg-type]
        MemoryUserRepository(),  # replaced by the SQL repository when the database wave lands
        OtpService(settings.SECRET_KEY + ":email"),
        OtpService(settings.SECRET_KEY + ":sms"),
        email_sender,
        sms_sender,
    )
    graph = build_graph({}, checkpointer=_checkpointer(settings.REDIS_URL, prod))
    vault = PiiVault(cipher, MemoryVaultStore())
    return Services(
        chat=ChatService(graph, vault),
        sessions=SessionService(MemorySessionRepository()),
        identity=identity,
        metrics_token=settings.METRICS_TOKEN,
    )


def create():
    """ASGI factory: `uvicorn --factory mpd_assistant.api.app:create`."""
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    setup_tracing("mpd-api")
    return create_app(build_services())
