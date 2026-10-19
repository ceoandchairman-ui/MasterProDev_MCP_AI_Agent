"""Staff-facing operations: the escalation inbox and a small overview. Every staff action is written to the audit log."""

import logging
from collections.abc import Callable
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
    ):
        self._service, self._repo, self._audit = escalations, repo, audit
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

    def overview(self) -> Dict:
        return {"open_escalations": len(self._repo.list_open()), "links": {k: v for k, v in self._links.items() if v}}


__all__ = ["AdminService", "EscalationView", "SqlAuditLog"]
