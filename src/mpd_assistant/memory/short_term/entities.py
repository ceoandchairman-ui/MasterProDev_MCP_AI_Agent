"""Entity and reference tracking: resolves "that email", "the meeting", "her" to what the conversation last touched.

Entities are registered by code (tool results, bookings, quotes), never copied from model output. Only ids, privacy
tokens and short non-personal labels are stored, so the table holds no raw contact details.
"""

import re
import time
from dataclasses import asdict, dataclass
from typing import Dict, List

from mpd_assistant.core.kv import KeyValueStore

TTL_SECONDS = 24 * 3600
MAX_PER_KIND = 5
MAX_LABEL = 80

KINDS = ("email", "meeting", "person", "quote", "document")

_PHRASES: Dict[str, re.Pattern] = {
    "email": re.compile(r"(?i)\b(that|the|this|last|cet?te?|le dernier|l[ae]) (e-?mail|message|courriel|mail)\b"),
    "meeting": re.compile(r"(?i)\b(that|the|this|cet?te?|l[ae]) (meeting|call|appointment|event|réunion|rendez-vous|événement)\b"),
    "person": re.compile(r"(?i)\b(her|him|them|that person|this person|elle|lui|cette personne|cet? (homme|femme))\b"),
    "quote": re.compile(r"(?i)\b(that|the|this|cet?te?|l[ae]) (quote|estimate|proposal|devis|soumission)\b"),
    "document": re.compile(r"(?i)\b(that|the|this|cet?te?|l[ae]) (file|document|attachment|pdf|fichier|pièce jointe)\b"),
}
_IT = re.compile(r"(?i)\b(it|that one|celui-là|celle-là|ça)\b")


@dataclass
class Entity:
    kind: str
    ref: str  # an id or a privacy token such as <EMAIL_1>; never a raw value
    label: str = ""
    seen_at: float = 0.0


class EntityTracker:
    def __init__(self, kv: KeyValueStore, clock=time.time):
        self._kv, self._clock = kv, clock

    def _key(self, thread_id: str) -> str:
        return f"entities:{thread_id}"

    def _load(self, thread_id: str) -> List[Entity]:
        return [Entity(**row) for row in (self._kv.get(self._key(thread_id)) or [])]

    def _save(self, thread_id: str, entities: List[Entity]) -> None:
        self._kv.set(self._key(thread_id), [asdict(e) for e in entities], TTL_SECONDS)

    def remember(self, thread_id: str, kind: str, ref: str, label: str = "") -> bool:
        if kind not in KINDS or not ref:
            return False
        entities = [e for e in self._load(thread_id) if not (e.kind == kind and e.ref == ref)]
        entities.append(Entity(kind, ref, label[:MAX_LABEL], self._clock()))
        same_kind = [e for e in entities if e.kind == kind]
        if len(same_kind) > MAX_PER_KIND:
            drop = {id(e) for e in same_kind[: len(same_kind) - MAX_PER_KIND]}
            entities = [e for e in entities if id(e) not in drop]
        self._save(thread_id, entities)
        return True

    def recent(self, thread_id: str, kind: str | None = None) -> List[Entity]:
        entities = sorted(self._load(thread_id), key=lambda e: e.seen_at, reverse=True)
        return [e for e in entities if kind is None or e.kind == kind]

    def resolve(self, thread_id: str, text: str) -> List[Entity]:
        """Most recent entity per referenced kind; a bare "it" resolves only when exactly one kind is in play."""
        found: List[Entity] = []
        for kind, pattern in _PHRASES.items():
            if pattern.search(text or ""):
                latest = self.recent(thread_id, kind)
                if latest:
                    found.append(latest[0])
        if not found and _IT.search(text or ""):
            everything = self.recent(thread_id)
            if everything and len({e.kind for e in everything[:3]}) == 1:
                found.append(everything[0])
        return found

    def context_note(self, thread_id: str, text: str) -> str:
        resolved = self.resolve(thread_id, text)
        if not resolved:
            return ""
        parts = [f"{e.kind} {e.ref}" + (f" ({e.label})" if e.label else "") for e in resolved]
        return "Referenced earlier in this conversation: " + "; ".join(parts) + ". "

    def clear(self, thread_id: str) -> None:
        self._kv.delete(self._key(thread_id))


__all__ = ["Entity", "EntityTracker"]
