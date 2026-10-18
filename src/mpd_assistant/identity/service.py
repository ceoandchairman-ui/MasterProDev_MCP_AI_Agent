"""Sign-up and verification: email OTP plus SMS OTP, then a verified user record with encrypted contact data."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Dict, Optional, Protocol

from mpd_assistant.core.crypto import FieldCipher, blind_index
from mpd_assistant.identity.normalize import normalize_email, normalize_name, normalize_phone
from mpd_assistant.identity.otp import OtpError, OtpService


class Sender(Protocol):
    def send(self, target: str, code: str) -> None: ...


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
    def save(self, user: VerifiedUser) -> None: ...


class MemoryUserRepository:
    def __init__(self):
        self._by_email: Dict[str, VerifiedUser] = {}

    def find_by_email_index(self, index: str) -> Optional[VerifiedUser]:
        return self._by_email.get(index)

    def save(self, user: VerifiedUser) -> None:
        self._by_email[user.email_index] = user


@dataclass
class _Pending:
    name: str
    email: str
    phone: str
    email_ok: bool = False
    phone_ok: bool = False


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
    ):
        self._cipher, self._key, self._users = cipher, blind_key, users
        self._email_otp, self._sms_otp = email_otp, sms_otp
        self._email_sender, self._sms_sender = email_sender, sms_sender
        self._pending: Dict[str, _Pending] = {}

    def start(self, session_id: str, name: str, email: str, phone: str) -> None:
        """Validate input and send both codes. Responses never reveal whether the email already exists."""
        pending = _Pending(normalize_name(name), normalize_email(email), normalize_phone(phone))
        self._email_sender.send(pending.email, self._email_otp.issue(pending.email))
        self._sms_sender.send(pending.phone, self._sms_otp.issue(pending.phone))
        self._pending[session_id] = pending

    def verify(self, session_id: str, email_code: str, phone_code: str) -> Optional[VerifiedUser]:
        pending = self._pending.get(session_id)
        if pending is None:
            return None
        pending.email_ok = pending.email_ok or self._email_otp.verify(pending.email, email_code)
        pending.phone_ok = pending.phone_ok or self._sms_otp.verify(pending.phone, phone_code)
        if not (pending.email_ok and pending.phone_ok):
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
        del self._pending[session_id]
        return user


__all__ = ["IdentityService", "MemoryUserRepository", "OtpError", "Sender", "VerifiedUser"]
