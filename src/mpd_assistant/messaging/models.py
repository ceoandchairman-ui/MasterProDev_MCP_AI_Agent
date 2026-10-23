from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Protocol


class Channel(str, Enum):
    WEB = "web"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    VOICE = "voice"


class Purpose(str, Enum):
    TRANSACTIONAL = "transactional"  # OTPs, confirmations, receipts, escalation notices
    MARKETING = "marketing"  # follow-ups; needs consent


@dataclass(frozen=True)
class OutboundMessage:
    channel: Channel
    to: str  # E.164 phone for sms/whatsapp, normalized email for email
    template: str
    locale: str = "en"
    variables: Dict[str, str] = field(default_factory=dict)
    purpose: Purpose = Purpose.TRANSACTIONAL
    idempotency_key: str | None = None
    user_id: str | None = None
    subject: str | None = None  # email only
    body: str | None = None  # pre-rendered text for conversational replies; template is then only a label


@dataclass
class SendResult:
    status: str  # sent | skipped | blocked | failed
    provider_id: str | None = None
    reason: str = ""


class Provider(Protocol):
    """A provider turns rendered text into a delivered message on one or more channels."""

    channels: frozenset

    async def send(self, channel: Channel, to: str, body: str, subject: str | None = None) -> SendResult: ...


def mask(target: str) -> str:
    """Safe-to-log form of a phone number or email."""
    if "@" in target:
        name, _, domain = target.partition("@")
        return f"{name[:1]}***@{domain}"
    return f"***{target[-4:]}" if len(target) > 4 else "***"
