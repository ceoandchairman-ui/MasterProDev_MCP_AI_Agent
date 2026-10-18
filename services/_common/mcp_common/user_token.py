"""The calling user's Google access token for this request. Set by the base server from a header, never cached."""

from contextvars import ContextVar, Token
from typing import Optional

_user_token: ContextVar[Optional[str]] = ContextVar("google_user_token", default=None)
HEADER = "x-google-access-token"


def set_user_token(token: Optional[str]) -> Token:
    return _user_token.set(token)


def reset_user_token(marker: Token) -> None:
    _user_token.reset(marker)


def current_user_token() -> Optional[str]:
    return _user_token.get()
