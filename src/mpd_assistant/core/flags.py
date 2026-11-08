"""Deterministic percentage rollout for the strangler migration. The same key always lands in the same bucket."""

import hashlib


def bucket(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 100


def enabled_for(key: str, percent: int) -> bool:
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    return bucket(key) < percent
