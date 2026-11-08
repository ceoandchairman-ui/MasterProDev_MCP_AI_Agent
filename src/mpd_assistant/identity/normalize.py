import re

import phonenumbers

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")


class InvalidIdentifier(ValueError):
    pass


def normalize_email(raw: str) -> str:
    value = (raw or "").strip().lower()
    if len(value) > 254 or not _EMAIL_RE.match(value):
        raise InvalidIdentifier("Invalid email address")
    return value


def normalize_phone(raw: str, default_region: str = "CA") -> str:
    """Return E.164, e.g. +14165550123."""
    try:
        parsed = phonenumbers.parse((raw or "").strip(), default_region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidIdentifier("Invalid phone number") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidIdentifier("Invalid phone number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_name(raw: str) -> str:
    value = re.sub(r"\s+", " ", (raw or "").strip())
    if not value or len(value) > 120 or re.search(r"[<>{}\[\]\\/@]", value):
        raise InvalidIdentifier("Invalid name")
    return value
