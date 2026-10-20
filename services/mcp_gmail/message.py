"""Gmail message helpers: building outgoing mail safely and pulling readable text out of incoming mail. Pure functions."""

import base64
import html
import re
from email.message import EmailMessage
from typing import Any, Dict, List

from services._common.mcp_common.results import valid_email

MAX_RECIPIENTS = 10
MAX_SUBJECT = 200
MAX_BODY_SEND = 20000
MAX_BODY_READ = 8000

_TAGS = re.compile(r"<[^>]+>")
_BLOCKS = re.compile(r"(?is)<(script|style).*?>.*?</\1>")
_BREAKS = re.compile(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>")
_SPACES = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")


class InvalidMessage(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def parse_recipients(value: Any) -> List[str]:
    """A list of addresses, or one comma-separated string. Anything that is not a plain address is rejected."""
    if value in (None, ""):
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    addresses = [valid_email(item) for item in items if str(item).strip()]
    if not all(addresses) or len(addresses) > MAX_RECIPIENTS:
        raise InvalidMessage("invalid_recipients")
    return [a for a in addresses if a]


def clean_subject(value: Any) -> str:
    subject = re.sub(r"[\r\n]+", " ", str(value or "")).strip()[:MAX_SUBJECT]
    if not subject:
        raise InvalidMessage("missing_subject")
    return subject


def build_message(params: Dict[str, Any]) -> EmailMessage:
    to = parse_recipients(params.get("to"))
    if not to:
        raise InvalidMessage("invalid_recipients")
    cc, bcc = parse_recipients(params.get("cc")), parse_recipients(params.get("bcc"))
    if len(to) + len(cc) + len(bcc) > MAX_RECIPIENTS:
        raise InvalidMessage("invalid_recipients")
    body = params.get("body")
    if not isinstance(body, str) or not body.strip():
        raise InvalidMessage("missing_body")
    message = EmailMessage()  # header values are validated by the email package, so a stray newline cannot add a header
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = clean_subject(params.get("subject"))
    message.set_content(body[:MAX_BODY_SEND])
    return message


def encode_raw(message: EmailMessage) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def _decode(data: str | None) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def html_to_text(markup: str) -> str:
    text = _BREAKS.sub("\n", _BLOCKS.sub(" ", markup))
    text = html.unescape(_TAGS.sub(" ", text))
    return _BLANKS.sub("\n\n", _SPACES.sub(" ", text)).strip()


def extract_body(payload: Dict[str, Any], limit: int = MAX_BODY_READ) -> str:
    """Prefers the plain-text part anywhere in a nested multipart message; falls back to the HTML part as text."""
    plain: List[str] = []
    markup: List[str] = []

    def walk(part: Dict[str, Any]) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if mime == "text/plain" and data:
            plain.append(_decode(data))
        elif mime == "text/html" and data:
            markup.append(_decode(data))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    text = "\n".join(plain).strip() or html_to_text("\n".join(markup))
    return text[:limit]


def headers_of(payload: Dict[str, Any]) -> Dict[str, str]:
    return {h.get("name", ""): h.get("value", "") for h in payload.get("headers", [])}
