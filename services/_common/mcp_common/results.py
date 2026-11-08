"""Small shared helpers so every tool server validates input and reports errors the same way.

Errors are short codes, never exception text: raw error strings can contain tokens, addresses or SQL.
"""

import re
from typing import Any, Dict

_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
_ID = re.compile(r"^[A-Za-z0-9_\-]{5,1024}$")


def ok(**data: Any) -> Dict[str, Any]:
    return {"status": "success", **data}


def fail(code: str, **extra: Any) -> Dict[str, Any]:
    return {"status": "error", "error": code, **extra}


def pending_auth(service: str) -> Dict[str, Any]:
    return {"status": "pending_auth", "message": f"{service} access has not been connected for this user."}


def int_in_range(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def clean_text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def valid_email(value: Any) -> str | None:
    if isinstance(value, str) and len(value) <= 254 and _EMAIL.match(value.strip()):
        return value.strip()
    return None


def valid_id(value: Any) -> str | None:
    return value if isinstance(value, str) and _ID.match(value) else None


def missing(params: Dict[str, Any], *names: str) -> str | None:
    for name in names:
        if params.get(name) in (None, ""):
            return name
    return None
