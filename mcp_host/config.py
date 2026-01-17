from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""

    # Server
    ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ALLOWED_ORIGINS: list = ["*"]
    SECRET_KEY: str = "your-secret-key-change-in-production"
    PUBLIC_DOMAIN: str = "http://localhost:8000"  # Set to your Railway domain in production

    # Database
    DATABASE_URL: str = "postgresql://mcpagent:mcpagent_dev_password@postgres:5432/mcpagent"

    # Redis
    REDIS_URL: str = "redis://:mcpagent_dev_password@redis:6379/0"
    REDIS_PASSWORD: str = "mcpagent_dev_password"
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # AWS Bedrock
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    BEDROCK_MODEL: str = "amazon.nova-pro-v1:0"

    # Security
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # MCP Servers
    CALENDAR_SERVER_URL: str = "http://calendar-server:8001"
    GMAIL_SERVER_URL: str = "http://gmail-server:8002"

    # HuggingFace LLM
    HUGGINGFACE_API_KEY: Optional[str] = None
    HUGGINGFACE_MODEL: Optional[str] = None
    ACTIVE_LLM_PROVIDER: Optional[str] = None

    # Google OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_OAUTH_REDIRECT_URI: Optional[str] = None

    # Weaviate
    WEAVIATE_HOST: str = "weaviate"
    WEAVIATE_PORT: int = 8080
    WEAVIATE_GRPC_PORT: int = 50051

    # Knowledge Base
    KNOWLEDGE_BASE_PATH: str = "knowledge_base"
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore"  # Ignore extra fields from .env
    }


# Global settings instance
settings = Settings()

# Debug: Print after settings are loaded (after .env is parsed)
print(f"[DEBUG] Settings.HUGGINGFACE_API_KEY: {settings.HUGGINGFACE_API_KEY}")
print(f"[DEBUG] Settings.ACTIVE_LLM_PROVIDER: {settings.ACTIVE_LLM_PROVIDER}")
