"""Free-slot arithmetic for the calendar service. Pure functions: no Google calls, easy to test."""

from datetime import datetime, time, timedelta
from typing import Dict, List, Sequence, Tuple
from zoneinfo import ZoneInfo

Interval = Tuple[datetime, datetime]

MAX_WINDOW_DAYS = 14
MAX_SLOTS = 20


def parse_moment(value: str, tz: ZoneInfo) -> datetime:
    """ISO 8601 with or without an offset. A value without an offset is read in the caller's zone."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)


def merge_busy(busy: Sequence[Interval]) -> List[Interval]:
    merged: List[Interval] = []
    for start, end in sorted(busy, key=lambda i: i[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def free_slots(
    busy: Sequence[Interval],
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
    tz: ZoneInfo,
    day_start: time = time(9, 0),
    day_end: time = time(17, 0),
    weekdays_only: bool = True,
    step: timedelta = timedelta(minutes=30),
    max_slots: int = MAX_SLOTS,
) -> List[Dict[str, str]]:
    """Slots of `duration` inside working hours that do not overlap any busy interval."""
    if duration <= timedelta(0) or window_end <= window_start:
        return []
    window_end = min(window_end, window_start + timedelta(days=MAX_WINDOW_DAYS))
    blocks = merge_busy(busy)
    slots: List[Dict[str, str]] = []
    day = window_start.astimezone(tz).date()
    last_day = window_end.astimezone(tz).date()
    while day <= last_day and len(slots) < max_slots:
        if not (weekdays_only and day.weekday() >= 5):
            open_at = max(datetime.combine(day, day_start, tzinfo=tz), window_start)
            close_at = min(datetime.combine(day, day_end, tzinfo=tz), window_end)
            cursor = open_at
            while cursor + duration <= close_at and len(slots) < max_slots:
                end = cursor + duration
                clash = next((b for b in blocks if b[0] < end and b[1] > cursor), None)
                if clash is None:
                    slots.append({"start": cursor.isoformat(), "end": end.isoformat()})
                    cursor += max(step, duration)
                else:
                    cursor = max(cursor + step, clash[1])
        day += timedelta(days=1)
    return slots
