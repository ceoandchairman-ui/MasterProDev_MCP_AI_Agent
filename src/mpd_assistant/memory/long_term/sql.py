"""Postgres-backed memory repository: any replica sees the same memories."""

from typing import List

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.db import from_epoch, to_epoch
from mpd_assistant.core.models import MemoryRow
from mpd_assistant.memory.long_term.store import Memory


def _to_domain(row: MemoryRow) -> Memory:
    return Memory(
        id=row.id,
        user_id=row.user_id,
        kind=row.kind,
        text=row.text,
        importance=row.importance,
        confidence=row.confidence,
        slot=row.slot,
        created_at=to_epoch(row.created_at) or 0.0,
        valid_to=to_epoch(row.valid_to),
        last_used=to_epoch(row.last_used),
        uses=row.uses,
        superseded_by=row.superseded_by,
    )


class SqlMemoryRepository:
    def __init__(self, engine: Engine):
        self._engine = engine

    def load_user(self, user_id: str) -> List[Memory]:
        with DbSession(self._engine) as db:
            return [_to_domain(r) for r in db.scalars(select(MemoryRow).where(MemoryRow.user_id == user_id))]

    def save(self, memory: Memory) -> None:
        with DbSession(self._engine) as db:
            row = db.get(MemoryRow, memory.id) or MemoryRow(id=memory.id, user_id=memory.user_id)
            row.kind, row.text = memory.kind, memory.text
            row.importance, row.confidence, row.slot = memory.importance, memory.confidence, memory.slot
            row.created_at = from_epoch(memory.created_at)
            row.valid_to, row.last_used = from_epoch(memory.valid_to), from_epoch(memory.last_used)
            row.uses, row.superseded_by = memory.uses, memory.superseded_by
            db.add(row)
            db.commit()

    def user_ids(self) -> List[str]:
        with DbSession(self._engine) as db:
            return list(db.scalars(select(MemoryRow.user_id).distinct()))

    def delete_user(self, user_id: str) -> int:
        with DbSession(self._engine) as db:
            count = db.execute(delete(MemoryRow).where(MemoryRow.user_id == user_id)).rowcount or 0
            db.commit()
            return count
