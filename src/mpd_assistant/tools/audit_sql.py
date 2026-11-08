"""Durable tool-call audit: which tool ran for which session, with redacted arguments and the outcome."""

import json

from sqlalchemy import Engine
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.logging import scrub
from mpd_assistant.core.models import ToolCall
from mpd_assistant.privacy.detector import redact


def _safe(value) -> dict:
    text = redact(scrub(json.dumps(value, default=str)))
    try:
        return json.loads(text)
    except ValueError:
        return {"redacted": text[:500]}


class SqlToolAudit:
    def __init__(self, engine: Engine):
        self._engine = engine

    def __call__(self, tool, args, ctx, outcome, latency_ms) -> None:
        if not ctx.session_row:
            return  # no session row to attach the record to
        with DbSession(self._engine) as db:
            db.add(
                ToolCall(
                    session_id=ctx.session_row,
                    tool=tool,
                    status=outcome.status,
                    input_redacted=_safe(args),
                    output_summary=(outcome.reason or str(sorted(outcome.output))[:200]) if outcome.status != "ok" else str(sorted(outcome.output))[:200],
                    latency_ms=latency_ms,
                )
            )
            db.commit()
