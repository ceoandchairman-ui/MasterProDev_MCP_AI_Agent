"""Inbound email channel (SendGrid Inbound Parse). Email is untrusted input, like any message: it goes through the
same pipeline as chat, a known sender's verified email maps to their account, and unknown senders stay visitors.

Loops are the main risk of an email bot, so automated mail (auto-replies, bulk, no-reply senders, our own address) is
dropped without an answer, and each sender is rate limited.
"""

import email.utils
import hmac
import re
from dataclasses import dataclass
from typing import Mapping, Optional

from mpd_assistant.core.crypto import blind_index
from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.normalize import InvalidIdentifier, normalize_email
from mpd_assistant.messaging.models import Channel, OutboundMessage, Purpose
from mpd_assistant.messaging.service import NotificationService, classify_keyword
from mpd_assistant.sessions.service import SessionService

MAX_BODY_CHARS = 4000
MAX_PER_HOUR = 10
SESSION_MAP_TTL = 7 * 24 * 3600
DEDUP_TTL = 7 * 24 * 3600

_AUTOMATED_SENDERS = re.compile(r"(?i)^(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounce|notifications?)[+@\-_.]")
_AUTOMATED_SUBJECT = re.compile(r"(?i)^\s*(out of office|automatic reply|auto(-|\s)?reply|réponse automatique|absence|undeliverable|delivery status)")
_QUOTE_MARKERS = [
    re.compile(r"(?im)^on .{5,120} wrote:\s*$"),
    re.compile(r"(?im)^le .{5,120} a écrit\s*:\s*$"),
    re.compile(r"(?im)^-{2,}\s*(original message|message d'origine|forwarded message)\s*-{2,}\s*$"),
    re.compile(r"(?im)^from:\s.+$"),
    re.compile(r"(?m)^--\s*$"),
    re.compile(r"(?im)^sent from my .+$"),
]


@dataclass(frozen=True)
class InboundEmail:
    sender: str  # normalized address
    subject: str
    text: str
    message_id: Optional[str] = None


def clean_body(text: str) -> str:
    """Keep only what the sender wrote: drop quoted replies, signatures and '>' quoted lines."""
    text = (text or "").replace("\r\n", "\n")
    cut = len(text)
    for marker in _QUOTE_MARKERS:
        match = marker.search(text)
        if match:
            cut = min(cut, match.start())
    kept = [line for line in text[:cut].split("\n") if not line.lstrip().startswith(">")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()[:MAX_BODY_CHARS]


def _header(raw_headers: str, name: str) -> str:
    match = re.search(rf"(?im)^{re.escape(name)}:\s*(.+)$", raw_headers or "")
    return match.group(1).strip() if match else ""


def is_automated(sender: str, subject: str, raw_headers: str, own_address: Optional[str] = None) -> bool:
    if own_address and sender == own_address.lower():
        return True
    if _AUTOMATED_SENDERS.match(sender) or _AUTOMATED_SUBJECT.match(subject or ""):
        return True
    auto = _header(raw_headers, "Auto-Submitted").lower()
    if auto and auto != "no":
        return True
    if _header(raw_headers, "Precedence").lower() in ("bulk", "junk", "list", "auto_reply"):
        return True
    return bool(_header(raw_headers, "X-Autoreply") or _header(raw_headers, "X-Autorespond") or _header(raw_headers, "List-Id"))


def parse_inbound_email(form: Mapping[str, str], own_address: Optional[str] = None) -> Optional[InboundEmail]:
    """None when the message should not be answered (unparseable, automated, or empty after cleaning)."""
    _, address = email.utils.parseaddr(form.get("from", ""))
    try:
        sender = normalize_email(address)
    except InvalidIdentifier:
        return None
    subject = (form.get("subject") or "").strip()[:200]
    raw_headers = form.get("headers", "")
    if is_automated(sender, subject, raw_headers, own_address):
        return None
    body = clean_body(form.get("text", ""))
    if not body:
        return None
    return InboundEmail(sender, subject, body, _header(raw_headers, "Message-ID") or None)


def valid_token(supplied: str, expected: Optional[str]) -> bool:
    """SendGrid Inbound Parse is not signed, so the webhook URL carries a secret token."""
    return bool(expected) and hmac.compare_digest(supplied.encode(), (expected or "").encode())


class EmailGateway:
    def __init__(
        self,
        chat: ChatService,
        sessions: SessionService,
        users,
        notifications: NotificationService,
        kv: KeyValueStore,
        blind_key: str,
        own_address: Optional[str] = None,
    ):
        self._chat, self._sessions, self._users = chat, sessions, users
        self._n, self._kv, self._key, self._own = notifications, kv, blind_key, own_address

    def _session_for(self, sender: str):
        index = blind_index(self._key, sender)
        user = self._users.find_by_email_index(index)
        map_key = f"chan:email:{index}"
        session_id = self._kv.get(map_key)
        session = self._sessions.resume(session_id) if session_id else None
        if session is None:
            session = self._sessions.create(user.id if user else None, verified=user is not None)
        elif user and not session.verified:
            session = self._sessions.upgrade_to_verified(session.id, user.id) or session
        self._kv.set(map_key, session.id, SESSION_MAP_TTL)
        return session

    async def handle(self, form: Mapping[str, str]) -> str:
        """Processes one inbound email. Returns a short status for logs/metrics: replied | ignored | duplicate | ..."""
        msg = parse_inbound_email(form, self._own)
        if msg is None:
            return "ignored"
        if msg.message_id and self._kv.incr(f"emailin:{msg.message_id}", DEDUP_TTL) > 1:
            return "duplicate"

        action = classify_keyword(msg.text.split("\n", 1)[0])
        if action == "opt_out":
            self._n.record_opt_out(Channel.EMAIL, msg.sender)
            return "opted_out"
        if action == "opt_in":
            self._n.clear_opt_out(Channel.EMAIL, msg.sender)
            return "opted_in"
        if self._kv.incr(f"inrate:email:{msg.sender}", 3600) > MAX_PER_HOUR:
            return "rate_limited"

        session = self._session_for(msg.sender)
        text = f"{msg.subject}\n\n{msg.text}" if msg.subject and not msg.subject.lower().startswith(("re:", "fwd:", "tr:")) else msg.text
        result = await self._chat.chat(session.thread_id, text, verified=session.verified, user_id=session.user_id, session_row=session.id)

        subject = msg.subject if msg.subject.lower().startswith("re:") else f"Re: {msg.subject or 'your message'}"
        sent = await self._n.send(
            OutboundMessage(
                Channel.EMAIL,
                msg.sender,
                "email_reply",
                "en",
                {},
                Purpose.TRANSACTIONAL,
                f"emailreply:{msg.message_id}" if msg.message_id else None,
                session.user_id,
                subject=subject,
                body=result.reply,
            )
        )
        return "replied" if sent.status in ("sent", "skipped") else f"reply_{sent.status}"


__all__ = ["EmailGateway", "InboundEmail", "clean_body", "is_automated", "parse_inbound_email", "valid_token"]
