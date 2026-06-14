"""Consecutive-workout-day streak over the manifest index.

The current streak ends at today OR yesterday — older trailing runs
report 0. The yesterday allowance keeps the sensor from flipping to 0
between midnight and the next morning's ride.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any


@dataclass(slots=True)
class StreakResult:
    current: int = 0
    longest: int = 0
    current_start: date | None = None
    last_workout_date: date | None = None


def _parse_local_date(starts: Any, tz: tzinfo) -> date | None:
    if not isinstance(starts, str) or not starts:
        return None
    try:
        dt = datetime.fromisoformat(starts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(tz).date()


def compute_streak(
    workouts_index: dict[int, dict[str, Any]],
    today: date,
    tz: tzinfo,
) -> StreakResult:
    """Current + longest streak over the workouts index, in calendar days of ``tz``."""
    dates = {
        d
        for entry in workouts_index.values()
        if (d := _parse_local_date(entry.get("starts"), tz)) is not None
    }
    if not dates:
        return StreakResult()

    sorted_dates = sorted(dates)

    longest = 1
    run = 1
    for prev, cur in zip(sorted_dates, sorted_dates[1:], strict=False):
        if cur - prev == timedelta(days=1):
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    last_date = sorted_dates[-1]
    if (today - last_date).days > 1:
        return StreakResult(longest=longest, last_workout_date=last_date)

    current = 1
    cursor = last_date - timedelta(days=1)
    while cursor in dates:
        current += 1
        cursor -= timedelta(days=1)

    return StreakResult(
        current=current,
        longest=max(longest, current),
        current_start=last_date - timedelta(days=current - 1),
        last_workout_date=last_date,
    )
