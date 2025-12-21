"""Gmail server config"""

from pydantic_settings import BaseSettings
from typing import Optional


class GmailSettings(BaseSettings):
    """Gmail server settings"""

    HOST: str = "0.0.0.0"
    PORT: int = 8002
    DEBUG: bool = True
    
    # Google OAuth
    GOOGLE_CLIENT_ID: Optional[str] = ""
    GOOGLE_CLIENT_SECRET: Optional[str] = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/integrations/google/callback"
    
    # API Keys
    GMAIL_API_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


gmail_settings = GmailSettings()
