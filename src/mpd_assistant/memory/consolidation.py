"""Nightly consolidation: distill clusters of old episodes into one durable fact, then retire the episodes.

The model proposes the fact; MemoryStore.write validates it like any other candidate. Users without memory consent
are skipped, and a failed distillation leaves the episodes untouched.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import List

from mpd_assistant.agents.common import parse_json_object
from mpd_assistant.core.llm.client import LLM, LLMError
from mpd_assistant.memory.long_term.store import Candidate, Memory, MemoryStore, jaccard

logger = logging.getLogger(__name__)

MIN_AGE_DAYS = 14
MIN_CLUSTER = 3
CLUSTER_SIMILARITY = 0.3
MAX_CLUSTER = 8
_DAY = 86400.0

SYSTEM = (
    "These are notes from past conversations with one user. Write ONE durable fact or preference that they all "
    'support, under 200 characters, with no names, contact details or placeholders. Output ONLY JSON: '
    '{"text": str, "importance": 0-1, "confidence": 0-1} or {"text": ""} if there is no common durable point.'
)


@dataclass
class ConsolidationReport:
    users: int = 0
    clusters: int = 0
    facts_written: int = 0
    episodes_archived: int = 0
    forgotten: int = 0


def cluster_episodes(episodes: List[Memory], similarity: float = CLUSTER_SIMILARITY) -> List[List[Memory]]:
    """Greedy single-pass clustering by word overlap; deterministic for a given input order."""
    clusters: List[List[Memory]] = []
    for episode in sorted(episodes, key=lambda m: m.created_at):
        for cluster in clusters:
            if len(cluster) < MAX_CLUSTER and jaccard(cluster[0].text, episode.text) >= similarity:
                cluster.append(episode)
                break
        else:
            clusters.append([episode])
    return [c for c in clusters if len(c) >= MIN_CLUSTER]


class Consolidator:
    def __init__(self, store: MemoryStore, llm: LLM | None, has_consent: Callable[[str], bool], clock: Callable[[], float]):
        self._store, self._llm, self._consent, self._clock = store, llm, has_consent, clock

    async def run(self) -> ConsolidationReport:
        report = ConsolidationReport()
        for user_id in self._store.user_ids():
            if not self._consent(user_id):
                continue
            report.users += 1
            try:
                await self._user(user_id, report)
                report.forgotten += self._store.decay_and_forget(user_id)
            except Exception:
                logger.exception("Consolidation failed for one user; continuing")
        return report

    async def _user(self, user_id: str, report: ConsolidationReport) -> None:
        cutoff = self._clock() - MIN_AGE_DAYS * _DAY
        old = [m for m in self._store.active(user_id) if m.kind == "episode" and m.created_at <= cutoff]
        for cluster in cluster_episodes(old):
            report.clusters += 1
            candidate = await self._distill(cluster)
            if candidate is None:
                continue
            result = self._store.write(user_id, candidate, consent=True)
            if result.status in ("stored", "superseded", "duplicate"):
                report.facts_written += result.status != "duplicate"
                report.episodes_archived += self._store.archive(user_id, [m.id for m in cluster], result.memory.id if result.memory else None)

    async def _distill(self, cluster: List[Memory]) -> Candidate | None:
        if self._llm is None:
            return None
        notes = "\n".join(f"- {m.text}" for m in cluster)
        try:
            result = await self._llm.complete(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": notes}],
                tier="cheap",
                max_tokens=150,
                temperature=0.0,
            )
        except LLMError:
            return None
        parsed = parse_json_object(result.text) or {}
        text = parsed.get("text")
        if not isinstance(text, str) or not text.strip():
            return None

        def clamp(value, default):
            try:
                return max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                return default

        return Candidate("fact", text.strip(), importance=clamp(parsed.get("importance"), 0.6), confidence=clamp(parsed.get("confidence"), 0.7))


__all__ = ["ConsolidationReport", "Consolidator", "cluster_episodes"]
