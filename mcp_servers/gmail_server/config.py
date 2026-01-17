"""Gmail server config"""

from pydantic_settings import BaseSettings
from typing import Optional


class GmailSettings(BaseSettings):
    """Gmail server settings"""

    HOST: str = "0.0.0.0"
    PORT: int = 8002
    DEBUG: bool = False
    
    # Google OAuth - MUST be set via environment variables for security
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/integrations/google/callback"
    
    # API Keys
    GMAIL_API_KEY: Optional[str] = None

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore"
    }

    def __init__(self, **data):
        super().__init__(**data)
        # Warn if OAuth credentials not set (don't crash, just warn)
        if not self.GOOGLE_CLIENT_ID or not self.GOOGLE_CLIENT_SECRET:
            print(
                "⚠️  WARNING: Google OAuth credentials not fully configured. "
                "Gmail features will be limited until GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set."
            )


gmail_settings = GmailSettings()
