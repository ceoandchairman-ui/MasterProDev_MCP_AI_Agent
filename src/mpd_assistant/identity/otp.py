"""One-time codes for email and SMS verification. Codes are stored only as keyed hashes."""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

CODE_LENGTH = 6
CODE_TTL_SECONDS = 600
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60


@dataclass
class _Challenge:
    code_hash: str
    expires_at: float
    attempts: int = 0
    issued_at: float = 0.0


class OtpError(Exception):
    pass


class OtpService:
    """In-memory reference implementation; production swaps the dict for Redis with a TTL."""

    def __init__(self, secret: str, clock: Callable[[], float] = time.time):
        self._secret = secret.encode()
        self._clock = clock
        self._challenges: Dict[str, _Challenge] = {}

    def _hash(self, target: str, code: str) -> str:
        return hmac.new(self._secret, f"{target}:{code}".encode(), hashlib.sha256).hexdigest()

    def issue(self, target: str) -> str:
        """target is a normalized email or E.164 phone. Returns the code for the sender to deliver."""
        now = self._clock()
        existing = self._challenges.get(target)
        if existing and now - existing.issued_at < RESEND_COOLDOWN_SECONDS:
            raise OtpError("Please wait before requesting another code")
        code = "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))
        self._challenges[target] = _Challenge(self._hash(target, code), now + CODE_TTL_SECONDS, 0, now)
        return code

    def verify(self, target: str, code: str) -> bool:
        challenge: Optional[_Challenge] = self._challenges.get(target)
        if challenge is None:
            return False
        if self._clock() > challenge.expires_at or challenge.attempts >= MAX_ATTEMPTS:
            self._challenges.pop(target, None)
            return False
        challenge.attempts += 1
        if hmac.compare_digest(challenge.code_hash, self._hash(target, code.strip())):
            self._challenges.pop(target, None)
            return True
        return False
