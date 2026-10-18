"""Sign-up and verification: email OTP plus SMS OTP, then a verified user record with encrypted contact data."""

import inspect
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Dict, Optional, Protocol

from mpd_assistant.core.crypto import FieldCipher, blind_index
from mpd_assistant.core.kv import KeyValueStore, MemoryKV
from mpd_assistant.identity.normalize import normalize_email, normalize_name, normalize_phone
from mpd_assistant.identity.otp import OtpError, OtpService


class Sender(Protocol):
    def send(self, target: str, code: str): ...  # may be sync or async


@dataclass
class VerifiedUser:
    id: str
    name_enc: str
    email_enc: str
    email_index: str
    phone_enc: str
    phone_index: str
    verified_at: datetime


class UserRepository(Protocol):
    def find_by_email_index(self, index: str) -> Optional[VerifiedUser]: ...
    def find_by_phone_index(self, index: str) -> Optional[VerifiedUser]: ...
    def find_by_id(self, user_id: str) -> Optional[VerifiedUser]: ...
    def save(self, user: VerifiedUser) -> None: ...


class MemoryUserRepository:
    def __init__(self):
        self._by_email: Dict[str, VerifiedUser] = {}

    def find_by_email_index(self, index: str) -> Optional[VerifiedUser]:
        return self._by_email.get(index)

    def find_by_id(self, user_id: str) -> Optional[VerifiedUser]:
        return next((u for u in self._by_email.values() if u.id == user_id), None)

    def find_by_phone_index(self, index: str) -> Optional[VerifiedUser]:
        return next((u for u in self._by_email.values() if u.phone_index == index), None)

    def save(self, user: VerifiedUser) -> None:
        self._by_email[user.email_index] = user


PENDING_TTL_SECONDS = 900


@dataclass
class _Pending:
    name: str
    email: str
    phone: str
    email_ok: bool = False
    phone_ok: bool = False


async def _deliver(sender: Sender, target: str, code: str) -> None:
    result = sender.send(target, code)
    if inspect.isawaitable(result):
        await result


class IdentityService:
    def __init__(
        self,
        cipher: FieldCipher,
        blind_key: str,
        users: UserRepository,
        email_otp: OtpService,
        sms_otp: OtpService,
        email_sender: Sender,
        sms_sender: Sender,
        kv: Optional[KeyValueStore] = None,
        abuse=None,
    ):
        self._cipher, self._key, self._users = cipher, blind_key, users
        self._email_otp, self._sms_otp = email_otp, sms_otp
        self._email_sender, self._sms_sender = email_sender, sms_sender
        self._kv = kv if kv is not None else MemoryKV()
        self._abuse = abuse

    async def start(self, session_id: str, name: str, email: str, phone: str, client_ip: Optional[str] = None) -> None:
        """Validate input and send both codes. Responses never reveal whether the email already exists."""
        pending = _Pending(normalize_name(name), normalize_email(email), normalize_phone(phone))
        if self._abuse is not None:
            self._abuse.check(pending.phone, client_ip)
        await _deliver(self._email_sender, pending.email, self._email_otp.issue(pending.email))
        await _deliver(self._sms_sender, pending.phone, self._sms_otp.issue(pending.phone))
        self._save_pending(session_id, pending)

    def verify(self, session_id: str, email_code: str, phone_code: str) -> Optional[VerifiedUser]:
        pending = self._load_pending(session_id)
        if pending is None:
            return None
        pending.email_ok = pending.email_ok or self._email_otp.verify(pending.email, email_code)
        pending.phone_ok = pending.phone_ok or self._sms_otp.verify(pending.phone, phone_code)
        if not (pending.email_ok and pending.phone_ok):
            self._save_pending(session_id, pending)
            return None

        index = blind_index(self._key, pending.email)
        user = self._users.find_by_email_index(index)
        if user is None:
            user = VerifiedUser(
                id=uuid.uuid4().hex,
                name_enc=self._cipher.encrypt(pending.name),
                email_enc=self._cipher.encrypt(pending.email),
                email_index=index,
                phone_enc=self._cipher.encrypt(pending.phone),
                phone_index=blind_index(self._key, pending.phone),
                verified_at=datetime.now(UTC),
            )
            self._users.save(user)
        self._kv.delete(f"pending:{session_id}")
        return user

    # Pending sign-ups hold raw contact details, so they are encrypted before they reach a shared store.
    def _save_pending(self, session_id: str, pending: _Pending) -> None:
        self._kv.set(f"pending:{session_id}", self._cipher.encrypt(json.dumps(asdict(pending))), PENDING_TTL_SECONDS)

    def _load_pending(self, session_id: str) -> Optional[_Pending]:
        raw = self._kv.get(f"pending:{session_id}")
        return _Pending(**json.loads(self._cipher.decrypt(raw))) if raw else None


__all__ = ["IdentityService", "MemoryUserRepository", "OtpError", "Sender", "VerifiedUser"]
