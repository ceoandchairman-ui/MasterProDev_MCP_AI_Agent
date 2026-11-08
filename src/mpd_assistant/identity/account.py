"""Account security: step-up verification, profile edits, and contact changes that must be re-verified."""

import inspect
import json
from typing import Awaitable, Callable

from mpd_assistant.core.crypto import FieldCipher, blind_index
from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.identity.normalize import normalize_email, normalize_name, normalize_phone
from mpd_assistant.identity.otp import OtpService

STEP_UP_TTL_SECONDS = 15 * 60
CONTACT_CHANGE_TTL_SECONDS = 15 * 60

Notify = Callable[[str, str], Awaitable[None] | None]  # (kind, old_value) -> tell the old contact about the change


class AccountService:
    def __init__(
        self,
        users,
        cipher: FieldCipher,
        blind_key: str,
        kv: KeyValueStore,
        stepup_otp: OtpService,
        email_otp: OtpService,
        sms_otp: OtpService,
        email_sender,
        sms_sender,
        notify_change: Notify | None = None,
    ):
        self._users, self._cipher, self._key, self._kv = users, cipher, blind_key, kv
        self._stepup_otp, self._email_otp, self._sms_otp = stepup_otp, email_otp, sms_otp
        self._email_sender, self._sms_sender = email_sender, sms_sender
        self._notify = notify_change

    # --- step-up ---------------------------------------------------------------------------
    @staticmethod
    async def _send(sender, target: str, code: str) -> None:
        result = sender.send(target, code)
        if inspect.isawaitable(result):
            await result

    def mark_recent(self, session_id: str) -> None:
        self._kv.set(f"stepup:{session_id}", True, STEP_UP_TTL_SECONDS)

    def has_recent(self, session_id: str) -> bool:
        return bool(self._kv.get(f"stepup:{session_id}"))

    async def stepup_start(self, user_id: str) -> bool:
        user = self._users.find_by_id(user_id)
        if user is None:
            return False
        email = self._cipher.decrypt(user.email_enc)
        await self._send(self._email_sender, email, self._stepup_otp.issue(email))
        return True

    def stepup_verify(self, session_id: str, user_id: str, code: str) -> bool:
        user = self._users.find_by_id(user_id)
        if user is None or not self._stepup_otp.verify(self._cipher.decrypt(user.email_enc), code):
            return False
        self.mark_recent(session_id)
        return True

    # --- profile ----------------------------------------------------------------------------
    def update_name(self, user_id: str, name: str) -> None:
        self._users.update_contact(user_id, name_enc=self._cipher.encrypt(normalize_name(name)))

    # --- contact changes ---------------------------------------------------------------------
    async def contact_start(self, user_id: str, kind: str, value: str) -> None:
        """Validates the new value and sends a code to it. The reply never says whether the value is already in use."""
        normalized = normalize_email(value) if kind == "email" else normalize_phone(value)
        otp, sender = (self._email_otp, self._email_sender) if kind == "email" else (self._sms_otp, self._sms_sender)
        await self._send(sender, normalized, otp.issue(normalized))
        self._kv.set(f"contact-change:{user_id}", self._cipher.encrypt(json.dumps({"kind": kind, "value": normalized})), CONTACT_CHANGE_TTL_SECONDS)

    async def contact_verify(self, user_id: str, code: str) -> bool:
        raw = self._kv.get(f"contact-change:{user_id}")
        if not raw:
            return False
        pending = json.loads(self._cipher.decrypt(raw))
        kind, value = pending["kind"], pending["value"]
        otp = self._email_otp if kind == "email" else self._sms_otp
        if not otp.verify(value, code):
            return False
        index = blind_index(self._key, value)
        taken = self._users.find_by_email_index(index) if kind == "email" else self._users.find_by_phone_index(index)
        if taken is not None and taken.id != user_id:
            self._kv.delete(f"contact-change:{user_id}")
            return False  # same generic failure as a wrong code, so existing accounts cannot be probed
        user = self._users.find_by_id(user_id)
        old = self._cipher.decrypt(user.email_enc if kind == "email" else user.phone_enc)
        if kind == "email":
            self._users.update_contact(user_id, email_enc=self._cipher.encrypt(value), email_index=index)
        else:
            self._users.update_contact(user_id, phone_enc=self._cipher.encrypt(value), phone_index=index)
        self._kv.delete(f"contact-change:{user_id}")
        if self._notify is not None:
            result = self._notify(kind, old)
            if inspect.isawaitable(result):
                await result
        return True
