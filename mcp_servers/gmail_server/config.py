"""Gmail server config"""

from pydantic_settings import BaseSettings
from typing import Optional
import os


class GmailSettings(BaseSettings):
    """Gmail server settings"""

    HOST: str = os.getenv("GMAIL_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("GMAIL_PORT", "8002"))
    DEBUG: bool = os.getenv("GMAIL_DEBUG", "False").lower() == "true"
    
    # Google OAuth - MUST be set via environment variables for security
    GOOGLE_CLIENT_ID: Optional[str] = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: Optional[str] = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8002/callback")
    
    # API Keys
    GMAIL_API_KEY: Optional[str] = os.getenv("GMAIL_API_KEY")

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

    def __init__(self, **data):
        super().__init__(**data)
        # Validate required OAuth credentials
        if not self.GOOGLE_CLIENT_ID:
            raise ValueError(
                "GOOGLE_CLIENT_ID environment variable is required. "
                "Set it in .env file or as an environment variable."
            )
        if not self.GOOGLE_CLIENT_SECRET:
            raise ValueError(
                "GOOGLE_CLIENT_SECRET environment variable is required. "
                "Set it in .env file or as an environment variable."
            )


gmail_settings = GmailSettings()
