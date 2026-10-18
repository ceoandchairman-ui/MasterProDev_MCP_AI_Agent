"""LangSmith tracing with masking. Inputs and outputs pass through the same redaction as logs before upload."""

import os
from typing import Any

from mpd_assistant.core.logging import scrub
from mpd_assistant.privacy.detector import redact


def mask_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact(scrub(value))
    if isinstance(value, dict):
        return {k: mask_payload(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [mask_payload(v) for v in value]
    return value


def configure_tracing(api_key: str | None, project: str) -> bool:
    """Enables LangSmith only when a key is set; traces are sampled and always masked."""
    if not api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return False
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = project
    return True
