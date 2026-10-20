"""Task decomposition: a message asking for several things is split so each part reaches the agent that owns it.

Splitting is conservative. A message is only split when its parts route to different agents, and never when any
part is a request for a person (that always wins and is handled whole).
"""

import re
from typing import List

from mpd_assistant.routing.intents import Mode
from mpd_assistant.routing.router import route

MAX_TASKS = 3
MIN_WORDS = 3

_SPLIT = re.compile(
    r"(?<=[.?!;])\s+"
    r"|\s*,?\s+\b(?:and then|and also|and after that|after that|as well as|then|also|puis|et ensuite|et aussi|ensuite)\b\s+",
    re.IGNORECASE,
)


def split_tasks(text: str, *, verified: bool = False, language: str | None = None) -> List[str]:
    """Returns the sub-tasks in order, or [text] when the message should be handled as one."""
    parts = [p.strip(" ,.;") for p in _SPLIT.split(text or "") if p and p.strip(" ,.;")]
    parts = [p for p in parts if len(p.split()) >= MIN_WORDS]
    if len(parts) < 2:
        return [text]
    parts = parts[:MAX_TASKS]
    decisions = [route(p, verified=verified, language=language) for p in parts]
    if any(d.mode is Mode.ESCALATE for d in decisions):
        return [text]
    if len({d.agent for d in decisions}) < 2:
        return [text]
    return parts


__all__ = ["MAX_TASKS", "split_tasks"]
