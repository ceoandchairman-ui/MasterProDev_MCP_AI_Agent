"""Hybrid retrieval helpers: reciprocal rank fusion, reranking interface and grounding threshold."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Sequence

RRF_K = 60


@dataclass(frozen=True)
class Hit:
    doc_id: str
    text: str
    source: str
    score: float = 0.0


def reciprocal_rank_fusion(rankings: Sequence[Sequence[Hit]], k: int = RRF_K, top_n: Optional[int] = None) -> List[Hit]:
    """Fuse ranked lists (e.g. BM25 and vector). A document's fused score is sum(1 / (k + rank))."""
    scores: Dict[str, float] = {}
    first_seen: Dict[str, Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.doc_id] = scores.get(hit.doc_id, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(hit.doc_id, hit)
    fused = [Hit(h.doc_id, h.text, h.source, scores[h.doc_id]) for h in first_seen.values()]
    fused.sort(key=lambda h: (-h.score, h.doc_id))
    return fused[:top_n] if top_n else fused


class Reranker(Protocol):
    async def rerank(self, query: str, hits: List[Hit]) -> List[Hit]: ...


class NoopReranker:
    async def rerank(self, query: str, hits: List[Hit]) -> List[Hit]:
        return hits


@dataclass
class Grounding:
    hits: List[Hit]
    answerable: bool


MIN_RERANK_SCORE = 0.2


def ground(hits: List[Hit], min_score: float = MIN_RERANK_SCORE, min_hits: int = 1) -> Grounding:
    """Below the threshold the assistant must say it has no reliable answer instead of guessing."""
    strong = [h for h in hits if h.score >= min_score]
    return Grounding(strong, len(strong) >= min_hits)


def cite(hits: List[Hit]) -> List[str]:
    seen, sources = set(), []
    for h in hits:
        if h.source not in seen:
            seen.add(h.source)
            sources.append(h.source)
    return sources
