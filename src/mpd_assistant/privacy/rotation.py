"""Key rotation for encrypted fields and blind indexes. Both functions default to a dry run that changes nothing.

Encryption keys: put the new key first in DATA_ENCRYPTION_KEY and the old one in DATA_ENCRYPTION_KEYS_PREVIOUS, deploy,
run rotate_encryption, then remove the old key once the report shows nothing left on it.

Blind index key: an index is a keyed hash, so it cannot be converted, only recomputed from the decrypted value.
Run rotate_blind_indexes with the new key, and switch BLIND_INDEX_KEY to it in the same maintenance window.
"""

from dataclasses import dataclass, field
from typing import List

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.crypto import FieldCipher, blind_index
from mpd_assistant.core.models import OAuthToken, User

USER_FIELDS = ("name_enc", "email_enc", "phone_enc")


@dataclass
class RotationReport:
    dry_run: bool
    scanned: int = 0
    rotated: int = 0
    already_current: int = 0
    failed: List[str] = field(default_factory=list)  # row ids only, never values

    @property
    def clean(self) -> bool:
        return not self.failed


def rotate_encryption(engine: Engine, cipher: FieldCipher, dry_run: bool = True) -> RotationReport:
    report = RotationReport(dry_run)
    with DbSession(engine) as db:
        rows = [(u, USER_FIELDS) for u in db.scalars(select(User))] + [(t, ("refresh_enc",)) for t in db.scalars(select(OAuthToken))]
        for row, fields in rows:
            report.scanned += 1
            changed = False
            try:
                for name in fields:
                    value = getattr(row, name)
                    if cipher.uses_primary_key(value):
                        continue
                    setattr(row, name, cipher.encrypt(cipher.decrypt(value)))
                    changed = True
            except Exception:
                report.failed.append(str(row.id))
                db.expire(row)  # discard this row's partial changes; other rows are unaffected
                continue
            if changed:
                report.rotated += 1
            else:
                report.already_current += 1
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return report


def rotate_blind_indexes(engine: Engine, cipher: FieldCipher, new_key: str, dry_run: bool = True) -> RotationReport:
    report = RotationReport(dry_run)
    with DbSession(engine) as db:
        for user in db.scalars(select(User)):
            report.scanned += 1
            try:
                email, phone = cipher.decrypt(user.email_enc), cipher.decrypt(user.phone_enc)
            except Exception:
                report.failed.append(user.id)
                continue
            new_email, new_phone = blind_index(new_key, email), blind_index(new_key, phone)
            if (user.email_index, user.phone_index) == (new_email, new_phone):
                report.already_current += 1
                continue
            user.email_index, user.phone_index = new_email, new_phone
            report.rotated += 1
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return report


__all__ = ["RotationReport", "rotate_blind_indexes", "rotate_encryption"]
