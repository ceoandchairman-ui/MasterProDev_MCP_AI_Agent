"""Data-subject requests: export and erase one person's data across every store, with a verification report."""

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.crypto import FieldCipher, blind_index
from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.core.models import (
    AuditLog,
    Escalation,
    FunnelEvent,
    Lead,
    MemoryRow,
    OAuthToken,
    Quote,
    ToolCall,
    Turn,
    User,
)
from mpd_assistant.core.models import Session as SessionRow
from mpd_assistant.messaging.models import Channel


@dataclass
class ErasureReport:
    user_id: str
    deleted: Dict[str, int] = field(default_factory=dict)
    kv_keys_removed: int = 0
    memories_removed: int = 0
    vendors_to_notify: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.errors


class DataSubjectService:
    def __init__(self, engine: Engine, kv: KeyValueStore, cipher: FieldCipher, blind_key: str, memory_store=None):
        self._engine, self._kv, self._cipher, self._key = engine, kv, cipher, blind_key
        self._memory = memory_store

    # --- export -----------------------------------------------------------------------------
    def export(self, user_id: str) -> dict:
        with DbSession(self._engine) as db:
            user = db.get(User, user_id)
            if user is None:
                return {"user_id": user_id, "found": False}
            sessions = list(db.scalars(select(SessionRow).where(SessionRow.user_id == user_id)))
            session_ids = [s.id for s in sessions]
            turns = list(db.scalars(select(Turn).where(Turn.session_id.in_(session_ids)))) if session_ids else []
            leads = list(db.scalars(select(Lead).where(Lead.user_id == user_id)))
            return {
                "user_id": user_id,
                "found": True,
                "profile": {
                    "name": self._cipher.decrypt(user.name_enc),
                    "email": self._cipher.decrypt(user.email_enc),
                    "phone": self._cipher.decrypt(user.phone_enc),
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                    "memory_consent": user.memory_consent,
                },
                "sessions": [{"id": s.id, "created_at": s.created_at.isoformat() if s.created_at else None} for s in sessions],
                # Turn text is stored pseudonymized; the export carries the same tokens the database holds.
                "conversation": [{"session_id": t.session_id, "user": t.user_text, "assistant": t.reply_text, "at": t.created_at.isoformat() if t.created_at else None} for t in turns],
                "leads": [{"stage": lead.stage, "need": lead.need_summary, "timeline": lead.timeline, "budget": lead.budget_range} for lead in leads],
                "memories": self._memory.export(user_id) if self._memory else [],
            }

    # --- erasure ----------------------------------------------------------------------------
    def erase(self, user_id: str, *, phone: Optional[str] = None, email: Optional[str] = None) -> ErasureReport:
        """Hard-deletes personal rows. The audit entry keeps only the user id hash, never personal values."""
        report = ErasureReport(user_id)
        with DbSession(self._engine) as db:
            user = db.get(User, user_id)
            if user is not None:
                phone = phone or self._cipher.decrypt(user.phone_enc)
                email = email or self._cipher.decrypt(user.email_enc)
            sessions = list(db.scalars(select(SessionRow).where(SessionRow.user_id == user_id)))
            session_ids = [s.id for s in sessions]
            lead_ids = list(db.scalars(select(Lead.id).where(Lead.user_id == user_id)))

            def count(stmt, label: str):
                result = db.execute(stmt)
                report.deleted[label] = report.deleted.get(label, 0) + (result.rowcount or 0)

            if session_ids:
                count(delete(ToolCall).where(ToolCall.session_id.in_(session_ids)), "tool_calls")
                count(delete(Escalation).where(Escalation.session_id.in_(session_ids)), "escalations")
                count(delete(Turn).where(Turn.session_id.in_(session_ids)), "turns")
            if lead_ids:
                count(delete(FunnelEvent).where(FunnelEvent.lead_id.in_(lead_ids)), "funnel_events")
                count(delete(Quote).where(Quote.lead_id.in_(lead_ids)), "quotes")
            count(delete(MemoryRow).where(MemoryRow.user_id == user_id), "memories")
            count(delete(OAuthToken).where(OAuthToken.user_id == user_id), "oauth_tokens")
            count(delete(Lead).where(Lead.user_id == user_id), "leads")
            count(delete(SessionRow).where(SessionRow.user_id == user_id), "sessions")
            count(delete(User).where(User.id == user_id), "users")
            db.add(AuditLog(actor="privacy", action="erase", target=hashlib.sha256(user_id.encode()).hexdigest()[:16], detail={"deleted": dict(report.deleted)}))
            db.commit()

        report.kv_keys_removed = self._erase_kv(user_id, session_ids, phone, email, report)
        if self._memory is not None:
            report.memories_removed = self._memory.delete_all(user_id)
        report.vendors_to_notify = ["SendGrid (suppression list, if contacted)", "Twilio (opt-out record, if messages were sent)"]
        return report

    def _erase_kv(self, user_id: str, session_ids: List[str], phone: Optional[str], email: Optional[str], report: ErasureReport) -> int:
        keys: List[str] = []
        for sid in session_ids:
            keys += [f"vault:{sid}", f"pending:{sid}"]
        for target in (phone, email):
            if not target:
                continue
            digest = hashlib.sha256(target.encode()).hexdigest()[:32]
            keys += [f"otp-email:{digest}", f"otp-sms:{digest}"]
            for channel in (Channel.SMS, Channel.WHATSAPP, Channel.EMAIL):
                keys += [f"optout:{channel.value}:{target}", f"rate:{channel.value}:{target}", f"inrate:{channel.value}:{target}"]
            if phone and target == phone:
                for channel in (Channel.SMS, Channel.WHATSAPP):
                    keys.append(f"chan:{channel.value}:{blind_index(self._key, target)}")
        removed = 0
        for key in keys:
            try:
                self._kv.delete(key)
                removed += 1
            except Exception as exc:
                report.errors.append(f"kv:{type(exc).__name__}")
        return removed
