"""Staff-facing operations: the escalation inbox and a small overview. Every staff action is written to the audit log."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import Engine
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.business.escalations import Escalation, EscalationService
from mpd_assistant.core.models import AuditLog

logger = logging.getLogger(__name__)

AuditSink = Callable[[str, str, Optional[str], Dict], None]


class SqlAuditLog:
    def __init__(self, engine: Engine):
        self._engine = engine

    def __call__(self, actor: str, action: str, target: Optional[str], detail: Dict) -> None:
        try:
            with DbSession(self._engine) as db:
                db.add(AuditLog(actor=actor[:64], action=action[:60], target=(target or "")[:64] or None, detail=detail))
                db.commit()
        except Exception:
            logger.exception("audit log write failed")  # never block a staff action on logging


@dataclass
class EscalationView:
    reference: str
    reason: str
    status: str
    created_at: str
    summary: str


def _view(e: Escalation) -> EscalationView:
    return EscalationView(e.reference, e.reason, e.status, e.created_at.isoformat(), e.summary)


class AdminService:
    def __init__(
        self,
        escalations: EscalationService,
        repo,
        audit: Optional[AuditSink] = None,
        grafana_url: Optional[str] = None,
        langsmith_url: Optional[str] = None,
        patterns=None,
        cache_purgers: Optional[Dict[str, Callable[[], Awaitable[int]]]] = None,
        people=None,
    ):
        self.people = people  # PeopleDirectory: audited lookup and merge of customer records
        self._service, self._repo, self._audit = escalations, repo, audit
        self._patterns = patterns
        self._purgers = cache_purgers or {}
        self._links = {"grafana": grafana_url, "langsmith": langsmith_url}

    def list_open(self) -> List[EscalationView]:
        return [_view(e) for e in sorted(self._repo.list_open(), key=lambda e: e.created_at)]

    def get(self, reference: str) -> Optional[EscalationView]:
        esc = self._repo.get(reference.upper())
        return _view(esc) if esc else None

    def resolve(self, reference: str, actor: str = "staff") -> bool:
        reference = reference.upper()
        done = self._service.resolve(reference)
        if done and self._audit:
            self._audit(actor, "escalation_resolved", reference, {})
        return done

    def pending_patterns(self) -> List[Dict]:
        if self._patterns is None:
            return []
        return [
            {"id": p.id, "intent": p.intent, "language": p.language, "user_text": p.user_text, "reply_text": p.reply_text}
            for p in self._patterns.pending()
        ]

    def review_pattern(self, pattern_id: str, approve: bool, actor: str = "staff") -> bool:
        if self._patterns is None:
            return False
        done = self._patterns.approve(pattern_id, actor) if approve else self._patterns.reject(pattern_id, actor)
        if done and self._audit:
            self._audit(actor, "pattern_approved" if approve else "pattern_rejected", pattern_id, {})
        return done

    @property
    def cache_layers(self) -> List[str]:
        return sorted(self._purgers)

    async def purge_cache(self, layer: str, actor: str = "staff") -> Optional[int]:
        """Clears one cache layer (response, semantic, retrieval). Returns entries removed, or None for an unknown layer."""
        purge = self._purgers.get(layer)
        if purge is None:
            return None
        removed = await purge()
        if self._audit:
            self._audit(actor, "cache_purged", layer, {"removed": removed})
        return removed

    def overview(self) -> Dict:
        return {
            "open_escalations": len(self._repo.list_open()),
            "patterns_awaiting_review": len(self._patterns.pending(limit=201)) if self._patterns is not None else 0,
            "links": {k: v for k, v in self._links.items() if v},
        }


__all__ = ["AdminService", "EscalationView", "SqlAuditLog"]
