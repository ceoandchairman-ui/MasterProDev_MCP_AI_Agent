from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    PUBLIC_DOMAIN: str = "http://localhost:8000"

    SECRET_KEY: str = Field(min_length=8)
    DATABASE_URL: str
    REDIS_URL: str
    REDIS_CACHE_URL: str | None = None
    DB_POOL_SIZE: int = 5  # replicas x (DB_POOL_SIZE + DB_MAX_OVERFLOW) must stay under Postgres max_connections
    DB_MAX_OVERFLOW: int = 5

    # Base64 urlsafe 32-byte keys; every one must be set explicitly in production.
    DATA_ENCRYPTION_KEY: str | None = None
    DATA_ENCRYPTION_KEYS_PREVIOUS: str = ""  # comma-separated old keys kept only so existing data still decrypts during rotation
    BLIND_INDEX_KEY: str | None = None
    MCP_SERVICE_KEY: str | None = None
    METRICS_TOKEN: str | None = None

    ACTIVE_LLM_PROVIDER: str = "huggingface"
    HUGGINGFACE_API_KEY: str | None = None
    HUGGINGFACE_MODEL: str | None = None
    LLM_BASE_URL: str = "https://router.huggingface.co/v1"
    LLM_MODEL_CHEAP: str | None = None
    LLM_MODEL_REASONING: str | None = None
    CATALOG_PATH: str | None = None
    JUDGE_SAMPLE_RATE: float = 0.2
    SESSION_DAILY_TOKENS: int = 60000
    GLOBAL_DAILY_TOKENS: int = 2000000
    ESCALATION_EMAIL: str | None = None
    CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_THRESHOLD: float = 0.92
    PROMPT_VERSION: str = "v1"
    CORPUS_VERSION: str = "1"
    SMS_ALLOWED_COUNTRIES: str = "CA,US"
    NEW_PIPELINE_PERCENT: int = 0
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_OAUTH_REDIRECT_URI: str | None = None
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_BASE_URL: str | None = None
    EMBEDDING_API_KEY: str | None = None
    RETRIEVAL_MIN_SCORE: float = 0.35
    RERANK_BASE_URL: str | None = None
    RERANK_API_KEY: str | None = None
    RERANK_MODEL: str = "rerank-multilingual-v3.0"
    RERANK_MIN_SCORE: float = 0.3
    KNOWLEDGE_BASE_PATH: str = "Company_Documents"
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_SMS_FROM: str | None = None
    TWILIO_WHATSAPP_FROM: str | None = None
    SENDGRID_API_KEY: str | None = None
    EMAIL_FROM: str | None = None
    MESSAGES_DAILY_CAP: int = 500
    CONVERSATION_RETENTION_DAYS: int = 365
    GUEST_RETENTION_DAYS: int = 30
    TRUSTED_PROXY_HOPS: int = 1  # Railway's edge is one proxy in front of the API
    EDGE_REQUESTS_PER_MINUTE: int = 120  # per client IP on chat and account routes; 0 turns it off
    CORS_ORIGINS: str = ""  # comma-separated site origins allowed to embed the widget
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    EMAIL_INBOUND_TOKEN: str | None = None
    ADMIN_TOKEN: str | None = None
    GRAFANA_URL: str | None = None
    LANGSMITH_URL: str | None = None
    STT_MODEL: str = "whisper-1"
    TTS_MODEL: str = "tts-1"
    AUDIO_BASE_URL: str | None = None
    AUDIO_API_KEY: str | None = None
    VISION_MODEL: str | None = None
    OCR_ENGINE: str = "none"  # none | tesseract | vision
    CALENDAR_SERVER_URL: str | None = None
    GMAIL_SERVER_URL: str | None = None
    DB_SERVER_URL: str | None = None  # the company-data tool service (read-only)
    PAYMENT_RETURN_URL: str | None = None  # where Stripe sends the customer after checkout; defaults to PUBLIC_DOMAIN
    USE_NEW_PIPELINE: bool = False

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() in ("production", "prod")

    def cipher_keys(self) -> list:
        """Current key first (it encrypts), then any previous keys (they only decrypt)."""
        previous = [k.strip() for k in self.DATA_ENCRYPTION_KEYS_PREVIOUS.split(",") if k.strip()]
        return [self.DATA_ENCRYPTION_KEY, *previous]

    def require_crypto_keys(self) -> None:
        missing = [k for k in ("DATA_ENCRYPTION_KEY", "BLIND_INDEX_KEY") if not getattr(self, k)]
        if missing:
            raise RuntimeError(f"Missing required keys: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
