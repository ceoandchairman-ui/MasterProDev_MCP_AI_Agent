"""Per-call Google access token, carried from the tool executor to the HTTP backend without touching arguments."""

from contextvars import ContextVar, Token
from typing import Optional

_access_token: ContextVar[Optional[str]] = ContextVar("google_access_token", default=None)


def set_token(token: Optional[str]) -> Token:
    return _access_token.set(token)


def reset_token(marker: Token) -> None:
    _access_token.reset(marker)


def current_token() -> Optional[str]:
    return _access_token.get()
