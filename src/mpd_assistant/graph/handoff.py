"""Handoff packet: what the next owner (another agent or a person) needs, in a size-capped, masked form."""

from typing import Any, Dict

MAX_PACKET_CHARS = 900
SLOTS = ("need", "timeline", "budget")
SHOWN_ONLY_WHEN_KNOWN = ("company",)


def build_packet(state: Dict[str, Any]) -> str:
    slots = state.get("lead_slots") or {}
    lines = []
    if state.get("intent"):
        lines.append(f"Intent: {state['intent']}")
    if state.get("lead_stage"):
        lines.append(f"Lead stage: {state['lead_stage']}")
    for slot in SLOTS:
        if slots.get(slot):
            lines.append(f"{slot.capitalize()}: {slots[slot]}")
    for slot in SHOWN_ONLY_WHEN_KNOWN:
        if slots.get(slot):
            lines.append(f"{slot.capitalize()}: {slots[slot]}")
    missing = [s for s in SLOTS if slots and s not in slots]
    if missing:
        lines.append("Still unknown: " + ", ".join(missing))
    if state.get("language"):
        lines.append(f"Language: {state['language']}")
    if state.get("pending_action"):
        lines.append(f"Waiting for the user to confirm: {state['pending_action'].get('tool')}")
    return "\n".join(lines)[:MAX_PACKET_CHARS]
