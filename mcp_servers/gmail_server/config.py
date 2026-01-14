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
