from mpd_assistant.routing.intents import Mode

_LADDER = [Mode.TEMPLATED, Mode.GENERATED, Mode.REASONED, Mode.ESCALATE]


def escalate_mode(mode: Mode) -> Mode:
    """Move one rung up the ladder (templated -> generated -> reasoned -> escalate)."""
    i = _LADDER.index(mode)
    return _LADDER[min(i + 1, len(_LADDER) - 1)]
