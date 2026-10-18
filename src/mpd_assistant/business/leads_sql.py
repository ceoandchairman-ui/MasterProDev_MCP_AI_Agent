from typing import Dict, Optional

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.models import FunnelEvent, Lead


class SqlLeadRepository:
    """One lead per verified user. Stage changes are appended to funnel_events for the funnel dashboard."""

    def __init__(self, engine: Engine, tenant_id: str):
        self._engine, self._tenant = engine, tenant_id

    def upsert(self, user_id: Optional[str], stage: str, slots: Dict[str, str]) -> None:
        if not user_id:
            return  # anonymous visitors are not stored as leads
        with DbSession(self._engine) as db:
            lead = db.scalar(select(Lead).where(Lead.tenant_id == self._tenant, Lead.user_id == user_id))
            previous = lead.stage if lead else None
            if lead is None:
                lead = Lead(tenant_id=self._tenant, user_id=user_id, stage=stage)
                db.add(lead)
                db.flush()
            lead.stage = stage
            lead.need_summary = slots.get("need")
            lead.timeline = slots.get("timeline")
            lead.budget_range = slots.get("budget")
            if previous != stage:
                db.add(FunnelEvent(lead_id=lead.id, from_stage=previous or "none", to_stage=stage))
            db.commit()
