"""Staff tools for the single customer record per person: look someone up by email or phone, find duplicates, merge them.

Every lookup and merge is written to the audit log. The audit entry holds a hash of the user id and the kind of lookup,
never the email or phone searched for. Staff see the name and masked contact details; full contact details stay in the
encrypted user record.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable, Dict, List

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.crypto import FieldCipher, blind_index
from mpd_assistant.core.models import FunnelEvent, Lead, MemoryRow, OAuthToken, User
from mpd_assistant.core.models import Quote as QuoteRow
from mpd_assistant.core.models import Session as SessionRow
from mpd_assistant.identity.normalize import InvalidIdentifier, normalize_email, normalize_phone
from mpd_assistant.messaging.models import mask

AuditSink = Callable[[str, str, str | None, Dict], None]


class MergeError(ValueError):
    pass


@dataclass
class PersonView:
    id: str
    name: str
    email: str  # masked
    phone: str  # masked
    role: str
    verified: bool
    memory_consent: bool
    lead_stage: str | None = None


@dataclass
class MergeReport:
    primary_id: str
    moved: Dict[str, int] = field(default_factory=dict)


def _ref(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


class PeopleDirectory:
    def __init__(self, engine: Engine, tenant_id: str, cipher: FieldCipher, blind_key: str, audit: AuditSink | None = None):
        self._engine, self._tenant, self._cipher, self._key, self._audit = engine, tenant_id, cipher, blind_key, audit

    def _log(self, actor: str, action: str, target: str | None, detail: Dict) -> None:
        if self._audit:
            self._audit(actor, action, target, detail)

    def _view(self, db: DbSession, user: User) -> PersonView:
        lead = db.scalar(select(Lead).where(Lead.tenant_id == self._tenant, Lead.user_id == user.id))
        return PersonView(
            id=user.id,
            name=self._cipher.decrypt(user.name_enc),
            email=mask(self._cipher.decrypt(user.email_enc)),
            phone=mask(self._cipher.decrypt(user.phone_enc)),
            role=user.role,
            verified=bool(user.email_verified_at and user.phone_verified_at),
            memory_consent=user.memory_consent,
            lead_stage=lead.stage if lead else None,
        )

    def lookup(self, *, email: str | None = None, phone: str | None = None, actor: str = "staff") -> PersonView | None:
        if bool(email) == bool(phone):
            raise InvalidIdentifier("Give either an email or a phone number")
        column, index = (User.email_index, blind_index(self._key, normalize_email(email))) if email else (User.phone_index, blind_index(self._key, normalize_phone(phone)))
        by = "email" if email else "phone"
        with DbSession(self._engine) as db:
            user = db.scalar(select(User).where(User.tenant_id == self._tenant, User.deleted_at.is_(None), column == index))
            if user is None:
                self._log(actor, "person_lookup", None, {"by": by, "found": False})
                return None
            view = self._view(db, user)
        self._log(actor, "person_lookup", _ref(view.id), {"by": by, "found": True})
        return view

    def duplicates(self) -> List[List[str]]:
        """Groups of user ids that share a phone number. Email is unique per tenant, so phone is where duplicates appear."""
        groups: Dict[str, List[str]] = defaultdict(list)
        with DbSession(self._engine) as db:
            for user in db.scalars(select(User).where(User.tenant_id == self._tenant, User.deleted_at.is_(None))):
                groups[user.phone_index].append(user.id)
        return [ids for ids in groups.values() if len(ids) > 1]

    def merge(self, primary_id: str, duplicate_id: str, actor: str = "staff") -> MergeReport:
        """Moves everything from the duplicate onto the primary, then retires the duplicate. The duplicate's email and phone
        stop resolving to anyone; the person keeps using the primary account."""
        if primary_id == duplicate_id:
            raise MergeError("Cannot merge a person into themselves")
        moved: Dict[str, int] = defaultdict(int)
        with DbSession(self._engine) as db:
            primary, dup = db.get(User, primary_id), db.get(User, duplicate_id)
            if primary is None or dup is None or primary.tenant_id != self._tenant or dup.tenant_id != self._tenant:
                raise MergeError("Both people must exist in this tenant")
            if primary.deleted_at is not None or dup.deleted_at is not None:
                raise MergeError("Cannot merge a retired account")

            moved["sessions"] = db.execute(update(SessionRow).where(SessionRow.user_id == dup.id).values(user_id=primary.id)).rowcount or 0
            moved["memories"] = db.execute(update(MemoryRow).where(MemoryRow.user_id == dup.id).values(user_id=primary.id)).rowcount or 0
            seen: set = set()
            for memory in list(db.scalars(select(MemoryRow).where(MemoryRow.user_id == primary.id).order_by(MemoryRow.created_at))):
                key = (memory.kind, " ".join(memory.text.lower().split()))
                if key in seen and memory.valid_to is None:
                    db.delete(memory)  # the same fact held by both accounts is kept once, oldest first
                    moved["memories_deduplicated"] += 1
                else:
                    seen.add(key)

            primary_providers = {t.provider for t in db.scalars(select(OAuthToken).where(OAuthToken.user_id == primary.id))}
            for token in list(db.scalars(select(OAuthToken).where(OAuthToken.user_id == dup.id))):
                if token.provider in primary_providers:
                    db.delete(token)  # one grant per provider; the primary's wins
                else:
                    token.user_id = primary.id
                    moved["oauth_grants"] += 1

            primary_lead = db.scalar(select(Lead).where(Lead.tenant_id == self._tenant, Lead.user_id == primary.id))
            dup_lead = db.scalar(select(Lead).where(Lead.tenant_id == self._tenant, Lead.user_id == dup.id))
            if dup_lead is not None:
                if primary_lead is None:
                    dup_lead.user_id = primary.id
                    moved["leads"] += 1
                else:
                    moved["quotes"] = db.execute(update(QuoteRow).where(QuoteRow.lead_id == dup_lead.id).values(lead_id=primary_lead.id)).rowcount or 0
                    moved["funnel_events"] = db.execute(update(FunnelEvent).where(FunnelEvent.lead_id == dup_lead.id).values(lead_id=primary_lead.id)).rowcount or 0
                    db.delete(dup_lead)

            dup.deleted_at = datetime.now(UTC)
            dup.email_index = f"merged:{dup.id}"
            dup.phone_index = f"merged:{dup.id}"
            db.commit()
        self._log(actor, "person_merged", _ref(primary_id), {"duplicate": _ref(duplicate_id), "moved": dict(moved)})
        return MergeReport(primary_id, dict(moved))


__all__ = ["MergeError", "MergeReport", "PeopleDirectory", "PersonView"]
