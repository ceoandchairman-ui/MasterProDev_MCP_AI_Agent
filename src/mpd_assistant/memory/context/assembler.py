"""Builds the prompt context under a token budget with a documented eviction order."""

from dataclasses import dataclass, field
from typing import Dict, List

from mpd_assistant.memory.short_term.window import estimate_tokens

# Prompt order. Stable content first keeps provider prompt-caching effective.
ORDER = ["stable_prefix", "thread_summary", "memories", "recent_window", "tool_digests"]

# What to drop first when over budget. "stable_prefix" is never dropped.
EVICTION_ORDER = ["tool_digests", "recent_window", "memories", "thread_summary"]

MEMORY_SHARE = 0.15


@dataclass
class Block:
    text: str
    score: float = 1.0  # relevance for memories; lower scores are dropped first
    pinned: bool = False


@dataclass
class Context:
    sections: Dict[str, List[Block]] = field(default_factory=dict)

    def tokens(self) -> int:
        return sum(estimate_tokens(b.text) for blocks in self.sections.values() for b in blocks)

    def render(self) -> str:
        parts = []
        for name in ORDER:
            for block in self.sections.get(name, []):
                parts.append(block.text)
        return "\n\n".join(parts)


def _section_tokens(blocks: List[Block]) -> int:
    return sum(estimate_tokens(b.text) for b in blocks)


def assemble(sections: Dict[str, List[Block]], budget_tokens: int) -> Context:
    ctx = Context({k: list(v) for k, v in sections.items()})

    # Memory never takes more than its share, regardless of overall pressure.
    memories = sorted(ctx.sections.get("memories", []), key=lambda b: (b.pinned, b.score), reverse=True)
    cap = int(budget_tokens * MEMORY_SHARE)
    kept, used = [], 0
    for block in memories:
        cost = estimate_tokens(block.text)
        if block.pinned or used + cost <= cap:
            kept.append(block)
            used += cost
    if "memories" in ctx.sections:
        ctx.sections["memories"] = kept

    for name in EVICTION_ORDER:
        while ctx.tokens() > budget_tokens:
            blocks = ctx.sections.get(name, [])
            droppable = [b for b in blocks if not b.pinned]
            if not droppable:
                break
            # Drop the oldest block for ordered sections, the lowest-scored for memories.
            victim = min(droppable, key=lambda b: b.score) if name == "memories" else droppable[0]
            blocks.remove(victim)
    return ctx
