"""Lead stage state machine. The LLM may propose a transition; code decides.

Stage names are defaults pending the business's own '3 Es' definition (see open questions).
"""

from enum import Enum
from typing import Dict, FrozenSet


class Stage(str, Enum):
    NEW = "new"
    ENGAGED = "engaged"
    QUALIFIED = "qualified"
    SCOPED = "scoped"
    QUOTED = "quoted"
    WON = "won"
    LOST = "lost"


_ALLOWED: Dict[Stage, FrozenSet[Stage]] = {
    Stage.NEW: frozenset({Stage.ENGAGED, Stage.LOST}),
    Stage.ENGAGED: frozenset({Stage.QUALIFIED, Stage.LOST}),
    Stage.QUALIFIED: frozenset({Stage.SCOPED, Stage.LOST}),
    Stage.SCOPED: frozenset({Stage.QUOTED, Stage.QUALIFIED, Stage.LOST}),
    Stage.QUOTED: frozenset({Stage.WON, Stage.SCOPED, Stage.LOST}),
    Stage.WON: frozenset(),
    Stage.LOST: frozenset({Stage.ENGAGED}),
}


class InvalidTransition(ValueError):
    pass


def can_transition(current: Stage, proposed: Stage) -> bool:
    return proposed in _ALLOWED[current]


def apply_transition(current: Stage, proposed: Stage) -> Stage:
    if not can_transition(current, proposed):
        raise InvalidTransition(f"{current.value} -> {proposed.value} is not allowed")
    return proposed
