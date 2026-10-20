"""The calling user's Google access token for this request. Set by the base server from a header, never cached."""

from contextvars import ContextVar, Token

_user_token: ContextVar[str | None] = ContextVar("google_user_token", default=None)
HEADER = "x-google-access-token"


def set_user_token(token: str | None) -> Token:
    return _user_token.set(token)


def reset_user_token(marker: Token) -> None:
    _user_token.reset(marker)


def current_user_token() -> str | None:
    return _user_token.get()
