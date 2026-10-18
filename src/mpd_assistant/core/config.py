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
