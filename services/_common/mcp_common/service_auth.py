"""Service-to-service authentication for MCP tool servers."""

import hmac
import os
from typing import Optional

from fastapi import HTTPException, Request

ALLOW_UNAUTH_ENV = "MCP_ALLOW_UNAUTHENTICATED"
SERVICE_KEY_ENV = "MCP_SERVICE_KEY"


def get_service_key() -> Optional[str]:
    return os.environ.get(SERVICE_KEY_ENV) or None


def unauthenticated_allowed() -> bool:
    return os.environ.get(ALLOW_UNAUTH_ENV, "").lower() in ("1", "true", "yes")


def check_startup_config() -> None:
    """Fail closed: refuse to start without a key unless explicitly opted out."""
    if not get_service_key() and not unauthenticated_allowed():
        raise RuntimeError(
            f"{SERVICE_KEY_ENV} is not set. Set it, or set {ALLOW_UNAUTH_ENV}=true for local development only."
        )


def keys_match(provided: Optional[str], expected: str) -> bool:
    if not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def _bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return None


async def require_service_auth(request: Request) -> None:
    """FastAPI dependency: rejects callers that do not present the shared service key."""
    expected = get_service_key()
    if expected is None:
        if unauthenticated_allowed():
            return
        raise HTTPException(status_code=503, detail="Service authentication is not configured")
    if not keys_match(_bearer_token(request), expected):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"})
