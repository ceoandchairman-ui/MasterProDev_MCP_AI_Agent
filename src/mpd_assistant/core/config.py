from functools import lru_cache
from typing import Optional

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
    REDIS_CACHE_URL: Optional[str] = None

    # Base64 urlsafe 32-byte keys; every one must be set explicitly in production.
    DATA_ENCRYPTION_KEY: Optional[str] = None
    BLIND_INDEX_KEY: Optional[str] = None
    MCP_SERVICE_KEY: Optional[str] = None
    METRICS_TOKEN: Optional[str] = None

    ACTIVE_LLM_PROVIDER: str = "huggingface"
    HUGGINGFACE_API_KEY: Optional[str] = None
    HUGGINGFACE_MODEL: Optional[str] = None
    LLM_BASE_URL: str = "https://router.huggingface.co/v1"
    LLM_MODEL_CHEAP: Optional[str] = None
    LLM_MODEL_REASONING: Optional[str] = None
    CATALOG_PATH: Optional[str] = None
    JUDGE_SAMPLE_RATE: float = 0.2
    SESSION_DAILY_TOKENS: int = 60000
    GLOBAL_DAILY_TOKENS: int = 2000000
    ESCALATION_EMAIL: Optional[str] = None
    CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_THRESHOLD: float = 0.92
    PROMPT_VERSION: str = "v1"
    CORPUS_VERSION: str = "1"
    SMS_ALLOWED_COUNTRIES: str = "CA,US"
    NEW_PIPELINE_PERCENT: int = 0
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_OAUTH_REDIRECT_URI: Optional[str] = None
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_BASE_URL: Optional[str] = None
    EMBEDDING_API_KEY: Optional[str] = None
    RETRIEVAL_MIN_SCORE: float = 0.35
    RERANK_BASE_URL: Optional[str] = None
    RERANK_API_KEY: Optional[str] = None
    RERANK_MODEL: str = "rerank-multilingual-v3.0"
    RERANK_MIN_SCORE: float = 0.3
    KNOWLEDGE_BASE_PATH: str = "Company_Documents"
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_SMS_FROM: Optional[str] = None
    TWILIO_WHATSAPP_FROM: Optional[str] = None
    SENDGRID_API_KEY: Optional[str] = None
    EMAIL_FROM: Optional[str] = None
    MESSAGES_DAILY_CAP: int = 500
    CONVERSATION_RETENTION_DAYS: int = 365
    GUEST_RETENTION_DAYS: int = 30
    TRUSTED_PROXY_HOPS: int = 1  # Railway's edge is one proxy in front of the API
    EDGE_REQUESTS_PER_MINUTE: int = 120  # per client IP on chat and account routes; 0 turns it off
    CORS_ORIGINS: str = ""  # comma-separated site origins allowed to embed the widget
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    EMAIL_INBOUND_TOKEN: Optional[str] = None
    ADMIN_TOKEN: Optional[str] = None
    GRAFANA_URL: Optional[str] = None
    LANGSMITH_URL: Optional[str] = None
    STT_MODEL: str = "whisper-1"
    TTS_MODEL: str = "tts-1"
    AUDIO_BASE_URL: Optional[str] = None
    AUDIO_API_KEY: Optional[str] = None
    VISION_MODEL: Optional[str] = None
    OCR_ENGINE: str = "none"  # none | tesseract | vision
    CALENDAR_SERVER_URL: Optional[str] = None
    GMAIL_SERVER_URL: Optional[str] = None
    USE_NEW_PIPELINE: bool = False

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() in ("production", "prod")

    def require_crypto_keys(self) -> None:
        missing = [k for k in ("DATA_ENCRYPTION_KEY", "BLIND_INDEX_KEY") if not getattr(self, k)]
        if missing:
            raise RuntimeError(f"Missing required keys: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
