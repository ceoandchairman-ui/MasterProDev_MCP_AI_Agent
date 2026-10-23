"""Vault storage on the shared key-value store. Values arrive already encrypted by the vault."""

from typing import Dict

from mpd_assistant.core.kv import KeyValueStore

VAULT_TTL_SECONDS = 7 * 24 * 3600  # placeholder retention until the owner sets one


class KvVaultStore:
    def __init__(self, kv: KeyValueStore, ttl_seconds: int = VAULT_TTL_SECONDS):
        self._kv, self._ttl = kv, ttl_seconds

    def load(self, session_id: str) -> Dict[str, str]:
        return self._kv.get(f"vault:{session_id}") or {}

    def save(self, session_id: str, data: Dict[str, str]) -> None:
        self._kv.set(f"vault:{session_id}", data, self._ttl)
