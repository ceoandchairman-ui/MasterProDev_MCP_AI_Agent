"""Inbound channels: normalize provider webhooks into one message type and format replies per channel."""

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Dict, Mapping, Optional
from xml.sax.saxutils import escape

from mpd_assistant.messaging.models import Channel

MAX_CHARS = {Channel.SMS: 1000, Channel.WHATSAPP: 1500, Channel.WEB: 4000, Channel.EMAIL: 8000, Channel.VOICE: 600}
_URL = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class InboundMessage:
    channel: Channel
    sender: str  # E.164 phone for sms/whatsapp
    text: str
    message_id: Optional[str] = None


def twilio_signature(auth_token: str, url: str, params: Mapping[str, str]) -> str:
    """Twilio request signature: HMAC-SHA1 over the URL plus sorted POST parameters, base64 encoded."""
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def validate_twilio_signature(auth_token: str, url: str, params: Mapping[str, str], signature: Optional[str]) -> bool:
    if not signature or not auth_token:
        return False
    return hmac.compare_digest(twilio_signature(auth_token, url, params), signature)


def parse_twilio_form(form: Mapping[str, str]) -> Optional[InboundMessage]:
    sender, body = form.get("From", ""), form.get("Body", "")
    if not sender or not body.strip():
        return None
    channel = Channel.SMS
    if sender.startswith("whatsapp:"):
        channel, sender = Channel.WHATSAPP, sender[len("whatsapp:") :]
    if not re.fullmatch(r"\+\d{8,15}", sender):
        return None
    return InboundMessage(channel, sender, body.strip()[:4000], form.get("MessageSid"))


_MARKDOWN = [(re.compile(r"\*\*(.+?)\*\*"), r"\1"), (re.compile(r"(?<!\w)\*(.+?)\*(?!\w)"), r"\1"), (re.compile(r"`([^`]*)`"), r"\1"), (re.compile(r"^#+\s*", re.M), "")]


def format_for_channel(text: str, channel: Channel) -> str:
    """Plain text for SMS/WhatsApp (no markdown), trimmed to a length the channel handles well."""
    if channel in (Channel.SMS, Channel.WHATSAPP, Channel.VOICE):
        for pattern, repl in _MARKDOWN:
            text = pattern.sub(repl, text)
    if channel is Channel.VOICE:
        text = _URL.sub("the link we sent you", text)  # links cannot be spoken
        text = re.sub(r"\s*\n+\s*", ". ", text)
    limit = MAX_CHARS[channel]
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def twiml_reply(text: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(text)}</Message></Response>'


def empty_twiml() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response/>'


__all__ = ["Dict", "InboundMessage", "format_for_channel", "parse_twilio_form", "twiml_reply", "validate_twilio_signature"]
