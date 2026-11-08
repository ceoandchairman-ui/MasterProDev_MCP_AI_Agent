"""Field encryption (Fernet) and keyed blind indexes for lookups on encrypted data."""

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


def generate_key() -> str:
    return Fernet.generate_key().decode()


class FieldCipher:
    """Authenticated encryption for sensitive fields. Supports key rotation: first key encrypts, all decrypt."""

    def __init__(self, *keys: str):
        if not keys:
            raise ValueError("At least one key is required")
        self._fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in keys]

    def encrypt(self, value: str) -> str:
        return self._fernets[0].encrypt(value.encode("utf-8")).decode()

    def uses_primary_key(self, token: str) -> bool:
        """True when the value is already encrypted under the current (first) key, so rotation can skip it."""
        try:
            self._fernets[0].decrypt(token.encode())
            return True
        except InvalidToken:
            return False

    def decrypt(self, token: str) -> str:
        for f in self._fernets:
            try:
                return f.decrypt(token.encode()).decode("utf-8")
            except InvalidToken:
                continue
        raise InvalidToken("Value could not be decrypted with any configured key")


def blind_index(key: str, normalized_value: str) -> str:
    """Deterministic keyed hash so equality lookups work without storing searchable plaintext."""
    raw = base64.urlsafe_b64decode(key.encode()) if _is_b64(key) else key.encode()
    return hmac.new(raw, normalized_value.encode("utf-8"), hashlib.sha256).hexdigest()


def _is_b64(value: str) -> bool:
    try:
        return len(base64.urlsafe_b64decode(value.encode())) >= 16
    except Exception:
        return False
