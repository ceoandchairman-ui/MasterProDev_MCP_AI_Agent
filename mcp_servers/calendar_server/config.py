"""Calendar server config"""

from pydantic_settings import BaseSettings
from typing import Optional


class CalendarSettings(BaseSettings):
    """Calendar server settings"""

    HOST: str = "0.0.0.0"
    PORT: int = 8001
    DEBUG: bool = True
    
    # Google OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/integrations/google/callback"
    
    # API Keys
    CALENDAR_API_KEY: Optional[str] = None

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore"
    }


calendar_settings = CalendarSettings()
