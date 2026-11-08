"""Sliding window with token-budget trimming that never separates a tool call from its result."""

from typing import Any, Dict, List

Message = Dict[str, Any]


def estimate_tokens(text: str) -> int:
    # Rough, language-agnostic estimate (about 4 characters per token); swapped for a real tokenizer later.
    return max(1, (len(text) + 3) // 4)


def message_tokens(msg: Message) -> int:
    return estimate_tokens(str(msg.get("content", ""))) + 4


def _group(messages: List[Message]) -> List[List[Message]]:
    """Group an assistant tool-call message with the tool results that answer it."""
    groups: List[List[Message]] = []
    for msg in messages:
        if msg.get("role") == "tool" and groups and groups[-1][0].get("tool_calls"):
            groups[-1].append(msg)
        else:
            groups.append([msg])
    return groups


def trim_to_budget(messages: List[Message], budget_tokens: int) -> List[Message]:
    """Keep the most recent groups that fit; pinned messages are always kept."""
    kept: List[List[Message]] = []
    used = 0
    pinned_cost = sum(message_tokens(m) for g in _group(messages) for m in g if m.get("pinned"))
    remaining = budget_tokens - pinned_cost

    for group in reversed(_group(messages)):
        if any(m.get("pinned") for m in group):
            kept.append(group)
            continue
        cost = sum(message_tokens(m) for m in group)
        if used + cost <= remaining:
            kept.append(group)
            used += cost
        elif not kept:
            # Always keep at least the latest group, truncated rather than dropped.
            last = dict(group[-1])
            last["content"] = str(last.get("content", ""))[: max(0, remaining) * 4]
            kept.append([last])
            used = remaining
            break
    kept.reverse()
    return [m for g in kept for m in g]
