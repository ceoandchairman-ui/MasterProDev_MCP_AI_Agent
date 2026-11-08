"""Reversible pseudonymization: the model sees tokens, tools and the user see real values."""

import re
from typing import Dict, Iterable, Protocol

from mpd_assistant.core.crypto import FieldCipher
from mpd_assistant.privacy.detector import detect

_TOKEN_RE = re.compile(r"<([A-Z_]+)_(\d+)>")


class VaultStore(Protocol):
    def load(self, session_id: str) -> Dict[str, str]: ...
    def save(self, session_id: str, data: Dict[str, str]) -> None: ...


class MemoryVaultStore:
    """Process-local store for tests and single-process use; production uses Redis with a TTL."""

    def __init__(self):
        self._data: Dict[str, Dict[str, str]] = {}

    def load(self, session_id: str) -> Dict[str, str]:
        return dict(self._data.get(session_id, {}))

    def save(self, session_id: str, data: Dict[str, str]) -> None:
        self._data[session_id] = dict(data)


class PiiVault:
    """Stable per-session tokens ('<EMAIL_1>'); real values are stored encrypted."""

    def __init__(self, cipher: FieldCipher, store: VaultStore, allowlist: Iterable[str] = ()):
        self._cipher = cipher
        self._store = store
        self._allowlist = list(allowlist)

    def tokenize(self, session_id: str, text: str) -> str:
        data = self._store.load(session_id)  # token -> encrypted value
        reverse = {self._cipher.decrypt(enc): tok for tok, enc in data.items()}
        counters: Dict[str, int] = {}
        for tok in data:
            m = _TOKEN_RE.fullmatch(tok)
            if m:
                counters[m.group(1)] = max(counters.get(m.group(1), 0), int(m.group(2)))

        out = text
        for m in reversed(detect(text, self._allowlist)):
            token = reverse.get(m.text)
            if token is None:
                counters[m.type] = counters.get(m.type, 0) + 1
                token = f"<{m.type}_{counters[m.type]}>"
                data[token] = self._cipher.encrypt(m.text)
                reverse[m.text] = token
            out = out[: m.start] + token + out[m.end :]
        self._store.save(session_id, data)
        return out

    def known_values(self, session_id: str) -> tuple:
        return tuple(self._cipher.decrypt(enc) for enc in self._store.load(session_id).values())

    def detokenize(self, session_id: str, text: str) -> str:
        """Replace only tokens this session issued; unknown tokens are left as-is."""
        data = self._store.load(session_id)

        def sub(match: re.Match) -> str:
            enc = data.get(match.group(0))
            return self._cipher.decrypt(enc) if enc else match.group(0)

        return _TOKEN_RE.sub(sub, text)
