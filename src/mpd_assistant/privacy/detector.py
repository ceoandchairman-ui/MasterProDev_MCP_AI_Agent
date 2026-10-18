"""PII detection. Fast, dependency-free recognizers; Presidio can be layered on top for names/addresses."""

import re
from dataclasses import dataclass
from typing import Iterable, List

EMAIL = "EMAIL"
PHONE = "PHONE"
CARD = "CARD"
SIN = "SIN"
POSTAL_CODE = "POSTAL_CODE"
SECRET = "SECRET"


@dataclass(frozen=True)
class Match:
    type: str
    start: int
    end: int
    text: str


def luhn_valid(digits: str) -> bool:
    nums = [int(d) for d in digits if d.isdigit()]
    if len(nums) < 9:
        return False
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<![\w@])(?:\+?\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\w)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")
_SIN_RE = re.compile(r"(?<!\d)\d{3}[ \-]?\d{3}[ \-]?\d{3}(?!\d)")
_POSTAL_RE = re.compile(r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d\b", re.I)
_SECRET_RE = re.compile(
    r"hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
)


def detect(text: str, allowlist: Iterable[str] = ()) -> List[Match]:
    """Return non-overlapping matches, most specific type first (secret > card > SIN > email > phone > postal)."""
    allowed = {a.lower() for a in allowlist}
    found: List[Match] = []

    def add(kind: str, pattern: re.Pattern, validator=None):
        for m in pattern.finditer(text):
            value = m.group(0)
            if value.lower() in allowed:
                continue
            if validator and not validator(value):
                continue
            found.append(Match(kind, m.start(), m.end(), value))

    add(SECRET, _SECRET_RE)
    add(CARD, _CARD_RE, lambda v: 13 <= len(re.sub(r"\D", "", v)) <= 19 and luhn_valid(v))
    # Grouped 3-3-3 numbers are flagged even when the check digit is wrong (fail closed); bare digits must pass Luhn.
    add(SIN, _SIN_RE, lambda v: luhn_valid(v) or bool(re.fullmatch(r"\d{3}[ -]\d{3}[ -]\d{3}", v)))
    add(EMAIL, _EMAIL_RE)
    add(PHONE, _PHONE_RE)
    add(POSTAL_CODE, _POSTAL_RE)

    priority = [SECRET, CARD, SIN, EMAIL, PHONE, POSTAL_CODE]
    found.sort(key=lambda m: (priority.index(m.type), m.start))
    accepted: List[Match] = []
    for m in found:
        if all(m.end <= a.start or m.start >= a.end for a in accepted):
            accepted.append(m)
    return sorted(accepted, key=lambda m: m.start)


def redact(text: str, allowlist: Iterable[str] = ()) -> str:
    """Irreversible masking for logs and telemetry."""
    out = text
    for m in reversed(detect(text, allowlist)):
        out = out[: m.start] + f"[{m.type}]" + out[m.end :]
    return out
