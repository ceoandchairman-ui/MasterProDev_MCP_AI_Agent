"""What an agent's prompt carries besides its own instructions: the recent turns, trimmed to a budget, and the check for
a follow-up question that cannot be searched on its own ("and how much is that?")."""

import re
from typing import Dict, List

from mpd_assistant.graph.state import AgentState
from mpd_assistant.memory.short_term.window import trim_to_budget

# Tokens of earlier conversation each agent may carry, and of background notes (summary, memories, files, style).
HISTORY_BUDGET = {"concierge": 600, "comms": 500, "lead": 300}
NOTE_BUDGET = {"concierge": 1800, "comms": 1200, "lead": 800}
MAX_TURNS = 8

_FOLLOW_UP = re.compile(
    r"^\s*(and|also|then|so|what about|how about|what if|et|et pour|et si|alors|quant)\b",
    re.IGNORECASE,
)
_REFERENCE = re.compile(
    r"\b(it|its|that|this|they|them|those|these|the same|the first|the second|the last|the other|ça|cela|ils|elles|celui|celle|le même|la même)\b",
    re.IGNORECASE,
)
SHORT_QUESTION_WORDS = 6


def recent_turns(state: AgentState, budget_tokens: int, max_turns: int = MAX_TURNS) -> List[Dict[str, str]]:
    """The turns before the current message, oldest first, as chat messages. Synthetic sub-task messages and anything that is
    not a user or assistant message are left out, and the window is trimmed to `budget_tokens`, keeping the newest."""
    messages = list(state.get("messages", []))
    last_user = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"), None)
    earlier = messages[:last_user] if last_user is not None else messages
    turns = [
        {"role": m["role"], "content": str(m["content"])}
        for m in earlier
        if m.get("role") in ("user", "assistant") and not m.get("synthetic") and str(m.get("content", "")).strip()
    ][-max_turns:]
    return [{"role": m["role"], "content": m["content"]} for m in trim_to_budget(turns, budget_tokens)]


def needs_rewrite(question: str, has_history: bool) -> bool:
    """True for a message that probably leans on earlier turns: very short, opening with a follow-up word, or pointing at
    something with a pronoun. A false positive costs one small extra model call; a miss costs a poor search."""
    if not has_history:
        return False
    text = question.strip()
    return len(text.split()) <= SHORT_QUESTION_WORDS or bool(_FOLLOW_UP.match(text)) or bool(_REFERENCE.search(text))


def transcript(turns: List[Dict[str, str]]) -> str:
    return "\n".join(f"{t['role']}: {t['content']}" for t in turns)


__all__ = ["HISTORY_BUDGET", "NOTE_BUDGET", "needs_rewrite", "recent_turns", "transcript"]
