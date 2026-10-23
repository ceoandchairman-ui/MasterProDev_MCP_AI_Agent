"""Fail-fast checks at startup. In production a missing secret stops the process instead of running half-configured."""

import os
from typing import Iterable, List

REQUIRED_PRODUCTION = (
    "SECRET_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "DATA_ENCRYPTION_KEY",
    "BLIND_INDEX_KEY",
    "MCP_SERVICE_KEY",
    "METRICS_TOKEN",
    "PUBLIC_DOMAIN",
)
PLACEHOLDER_MARKERS = ("change-me", "change-this", "ci-only", "your-", "example.com/")


def problems(env: dict, required: Iterable[str] = REQUIRED_PRODUCTION) -> List[str]:
    issues = []
    for name in required:
        value = (env.get(name) or "").strip()
        if not value:
            issues.append(f"{name} is not set")
        elif any(marker in value.lower() for marker in PLACEHOLDER_MARKERS):
            issues.append(f"{name} still holds a placeholder value")
    return issues


def assert_production_ready(env: dict | None = None) -> None:
    env = dict(os.environ if env is None else env)
    if env.get("ENV", "development").lower() not in ("production", "prod"):
        return
    issues = problems(env)
    if issues:
        raise RuntimeError("production configuration incomplete: " + "; ".join(issues))
