"""Memory evaluation: does recall find the right memory, stay quiet when nothing is relevant, avoid stale or
contradictory items, and stay within the token budget? Runs offline against an in-memory store.

Cases needing meaning-based matching (for example a French question about an English memory) set
`needs_embeddings: true`; they are skipped unless an embedder is supplied.
"""

from pathlib import Path
from typing import Any, Dict, List

import yaml

from mpd_assistant.memory.long_term.store import Candidate, MemoryStore
from mpd_assistant.memory.short_term.window import estimate_tokens
from mpd_assistant.retrieval.embeddings import Embedder

NOW = 1_800_000_000.0
DAY = 86400.0
TOKEN_BUDGET = 150
TOP_K = 3
STALE_RECENCY = 0.25  # recalled items whose recency factor is below this count as stale
USER = "eval-user"


class _Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self) -> float:
        return self.t


async def run_memory(path: Path, embedder: Embedder | None = None) -> Dict[str, Any]:
    cases: List[dict] = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]
    hits = positives = quiet = negatives = skipped = 0
    reciprocal: List[float] = []
    recalled_total = stale = 0
    token_costs: List[int] = []
    slots_total = slots_conflicted = 0
    failures: List[dict] = []

    for case in cases:
        if case.get("needs_embeddings") and embedder is None:
            skipped += 1
            continue
        clock = _Clock()
        store = MemoryStore(clock=clock)
        ids: Dict[str, str] = {}
        for item in case["memories"]:
            clock.t = NOW - float(item.get("age_days", 0)) * DAY
            result = store.write(USER, Candidate(item["kind"], item["text"], importance=float(item.get("importance", 0.6)), confidence=0.9, slot=item.get("slot"), language=item.get("language", "en")), consent=True)
            if result.memory is not None:
                ids[item["id"]] = result.memory.id
                if embedder is not None:
                    store.set_embedding(USER, result.memory.id, (await embedder.embed([item["text"]]))[0])
        clock.t = NOW

        vector = (await embedder.embed([case["query"]]))[0] if embedder is not None else None
        recalled = store.recall(USER, case["query"], TOKEN_BUDGET, limit=TOP_K, query_vector=vector)
        recalled_ids = [m.id for m in recalled]
        token_costs.append(sum(estimate_tokens(m.text) for m in recalled))
        for m in recalled:
            recalled_total += 1
            if store._recency(m, NOW) < STALE_RECENCY:  # noqa: SLF001 - the evaluator measures the store's own decay
                stale += 1

        active = store.active(USER)
        by_slot: Dict[str, int] = {}
        for m in active:
            if m.slot:
                by_slot[m.slot] = by_slot.get(m.slot, 0) + 1
        slots_total += len(by_slot)
        slots_conflicted += sum(1 for n in by_slot.values() if n > 1)

        expected = [ids[e] for e in case["expect"] if e in ids]
        if not case["expect"]:
            negatives += 1
            if not recalled_ids:
                quiet += 1
            else:
                failures.append({"id": case["id"], "problem": "recalled something for an unrelated question"})
        else:
            positives += 1
            rank = next((i + 1 for i, rid in enumerate(recalled_ids) if rid in expected), None)
            if rank is not None:
                hits += 1
                reciprocal.append(1 / rank)
            else:
                reciprocal.append(0.0)
                failures.append({"id": case["id"], "problem": f"expected {case['expect']} not in top {TOP_K}"})

    return {
        "suite": "memory",
        "cases": len(cases) - skipped,
        "skipped": skipped,
        "recall_at_k": hits / positives if positives else 1.0,
        "mrr": sum(reciprocal) / len(reciprocal) if reciprocal else 1.0,
        "no_noise_rate": quiet / negatives if negatives else 1.0,
        "stale_rate": stale / recalled_total if recalled_total else 0.0,
        "contradiction_rate": slots_conflicted / slots_total if slots_total else 0.0,
        "tokens_per_recall": sum(token_costs) / len(token_costs) if token_costs else 0.0,
        "failures": failures,
    }


__all__ = ["run_memory"]
