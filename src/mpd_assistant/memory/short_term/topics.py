"""Topic segmentation: notice when the user changes subject and park an unfinished task so it can be resumed."""

import re
from dataclasses import asdict, dataclass
from typing import List

from mpd_assistant.core.kv import KeyValueStore

TTL_SECONDS = 24 * 3600
MAX_PARKED = 3

_RESUME = re.compile(r"(?i)\b(back to|go back|as I was saying|continue with|resume|where were we|revenons|reprenons|on reprend)\b")
_STOP = frozenset("a an the and or to of in on for with is are was were be do does did i you we it this that my your our me can could would will please hi hello yes no ok okay de la le les un une et ou à en pour avec est sont je vous nous il elle ce cela mon votre notre".split())


def _terms(text: str) -> set:
    return {w for w in re.findall(r"\w{3,}", (text or "").lower()) if w not in _STOP}


def overlap(a: str, b: str) -> float:
    ta, tb = _terms(a), _terms(b)
    return len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0


@dataclass
class ParkedTask:
    intent: str
    summary: str


@dataclass
class TopicShift:
    shifted: bool
    resume: bool = False
    parked: ParkedTask | None = None


class TopicTracker:
    """Called once per turn with the routed intent. An intent change with no shared vocabulary is a topic shift."""

    def __init__(self, kv: KeyValueStore):
        self._kv = kv

    def _key(self, thread_id: str) -> str:
        return f"topic:{thread_id}"

    def _state(self, thread_id: str) -> dict:
        return self._kv.get(self._key(thread_id)) or {"intent": "", "text": "", "open": False, "parked": []}

    def observe(self, thread_id: str, intent: str, text: str, task_open: bool = False) -> TopicShift:
        state = self._state(thread_id)
        parked = [ParkedTask(**p) for p in state["parked"]]

        if _RESUME.search(text or "") and parked:
            task = parked.pop()
            state.update(intent=task.intent, text=task.summary, open=True, parked=[asdict(p) for p in parked])
            self._kv.set(self._key(thread_id), state, TTL_SECONDS)
            return TopicShift(True, resume=True, parked=task)

        shifted = bool(state["intent"]) and intent != state["intent"] and overlap(state["text"], text) < 0.2
        newly_parked = None
        if shifted and state["open"]:
            newly_parked = ParkedTask(state["intent"], state["text"][:200])
            parked = (parked + [newly_parked])[-MAX_PARKED:]
        state.update(intent=intent, text=text[:200], open=task_open, parked=[asdict(p) for p in parked])
        self._kv.set(self._key(thread_id), state, TTL_SECONDS)
        return TopicShift(shifted, parked=newly_parked)

    def parked(self, thread_id: str) -> List[ParkedTask]:
        return [ParkedTask(**p) for p in self._state(thread_id)["parked"]]

    def clear(self, thread_id: str) -> None:
        self._kv.delete(self._key(thread_id))


__all__ = ["ParkedTask", "TopicShift", "TopicTracker", "overlap"]
