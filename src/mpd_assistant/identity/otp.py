"""One-time codes for email and SMS verification. Codes are stored only as keyed hashes, in a shared store."""

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable

from mpd_assistant.core.kv import KeyValueStore, MemoryKV

CODE_LENGTH = 6
CODE_TTL_SECONDS = 600
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60


class OtpError(Exception):
    pass


class OtpService:
    """Challenges live in a KeyValueStore (Redis in deployments) so any replica can verify a code."""

    def __init__(self, secret: str, clock: Callable[[], float] = time.time, store: KeyValueStore | None = None, namespace: str = "otp"):
        self._secret = secret.encode()
        self._clock = clock
        self._store = store if store is not None else MemoryKV()
        self._ns = namespace

    def _key(self, target: str) -> str:
        return f"{self._ns}:{hashlib.sha256(target.encode()).hexdigest()[:32]}"  # no raw email/phone in store keys

    def _hash(self, target: str, code: str) -> str:
        return hmac.new(self._secret, f"{target}:{code}".encode(), hashlib.sha256).hexdigest()

    def issue(self, target: str) -> str:
        """target is a normalized email or E.164 phone. Returns the code for the sender to deliver."""
        now = self._clock()
        existing = self._store.get(self._key(target))
        if existing and now - existing["issued_at"] < RESEND_COOLDOWN_SECONDS:
            raise OtpError("Please wait before requesting another code")
        code = "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))
        challenge = {"code_hash": self._hash(target, code), "expires_at": now + CODE_TTL_SECONDS, "attempts": 0, "issued_at": now}
        self._store.set(self._key(target), challenge, CODE_TTL_SECONDS + 60)
        return code

    def verify(self, target: str, code: str) -> bool:
        key = self._key(target)
        challenge = self._store.get(key)
        if challenge is None:
            return False
        if self._clock() > challenge["expires_at"] or challenge["attempts"] >= MAX_ATTEMPTS:
            self._store.delete(key)
            return False
        challenge["attempts"] += 1
        if hmac.compare_digest(challenge["code_hash"], self._hash(target, code.strip())):
            self._store.delete(key)
            return True
        self._store.set(key, challenge, CODE_TTL_SECONDS + 60)
        return False
