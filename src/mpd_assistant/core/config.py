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
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_OAUTH_REDIRECT_URI: Optional[str] = None
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_BASE_URL: Optional[str] = None
    EMBEDDING_API_KEY: Optional[str] = None
    RETRIEVAL_MIN_SCORE: float = 0.35
    KNOWLEDGE_BASE_PATH: str = "Company_Documents"
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_SMS_FROM: Optional[str] = None
    TWILIO_WHATSAPP_FROM: Optional[str] = None
    SENDGRID_API_KEY: Optional[str] = None
    EMAIL_FROM: Optional[str] = None
    MESSAGES_DAILY_CAP: int = 500
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
