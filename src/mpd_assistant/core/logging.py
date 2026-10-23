"""Structured JSON logging that scrubs secrets before anything is written."""

import json
import logging
import re
from datetime import UTC, datetime

_SECRET_PATTERNS = [
    (re.compile(r"hf_[A-Za-z0-9]{20,}"), "hf_[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "sk-[REDACTED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA[REDACTED]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"), r"\1[REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[JWT_REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|secret|token|password|passwd)\s*[=:]\s*)[^\s,;\"']+"), r"\1[REDACTED]"),
]


def scrub(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class ScrubbingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.getMessage())
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": scrub(record.getMessage()),
        }
        for key in ("trace_id", "span_id", "session_id"):
            value = getattr(record, key, None)
            if value:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = scrub(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ScrubbingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
