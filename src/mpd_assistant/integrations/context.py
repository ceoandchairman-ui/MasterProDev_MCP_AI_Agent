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


_user_id: ContextVar[Optional[str]] = ContextVar("tool_user_id", default=None)


def set_user(user_id: Optional[str]) -> Token:
    return _user_id.set(user_id)


def reset_user(marker: Token) -> None:
    _user_id.reset(marker)


_untrusted: ContextVar[bool] = ContextVar("untrusted_in_context", default=False)


def set_untrusted(flag: bool) -> Token:
    return _untrusted.set(flag)


def reset_untrusted(marker: Token) -> None:
    _untrusted.reset(marker)


def untrusted_in_context() -> bool:
    """True when the model has read email bodies, uploads or retrieved text this turn."""
    return _untrusted.get()


def current_user() -> Optional[str]:
    """The user a local tool is running for. Tools never take the user id from model-written arguments."""
    return _user_id.get()
