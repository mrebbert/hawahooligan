"""Consecutive-workout-day streak calculator over the manifest index.

Pure module — no Home Assistant imports — so it's trivially testable in
Tier-1 via the same ``importlib`` trick the FIT parser uses.

The streak is a count of consecutive calendar days (in the user's local
TZ) with at least one workout. Multiple workouts on the same day still
count as one streak day. The "current" streak is only valid if it ends
**today or yesterday** — any older trailing run is treated as broken
(current = 0), so the sensor doesn't lie to a user who hasn't trained
in a week.

The yesterday allowance is deliberate: a user opening the dashboard at
06:00 the morning after a 30-day streak is still on a 30-day streak —
they just haven't done today's session yet. Without the allowance the
sensor would read 0 between midnight and tomorrow's training session,
which reads as "you broke your streak" when nothing happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any


@dataclass(slots=True)
class StreakResult:
    """Current streak + the historical max + bookkeeping dates.

    ``current_start`` is the first day of the current streak; ``None``
    when the current streak is 0. ``last_workout_date`` is the most
    recent date with ANY workout in the index — useful as an attribute
    for "when did I last train?" automations even when the streak has
    broken.
    """

    current: int = 0
    longest: int = 0
    current_start: date | None = None
    last_workout_date: date | None = None


def _parse_local_date(starts: Any, tz: tzinfo) -> date | None:
    """Parse Wahoo's ``starts`` ISO timestamp to a local date in ``tz``.

    Returns ``None`` for missing or malformed values — those workouts
    drop silently from the streak calculation rather than poisoning it
    with a default like "epoch 0".
    """
    if not isinstance(starts, str) or not starts:
        return None
    try:
        # Wahoo's ``Z`` UTC suffix isn't accepted by ``fromisoformat`` on
        # Python <3.11; the substitution makes it parse on every release.
        dt = datetime.fromisoformat(starts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(tz).date()


def compute_streak(
    workouts_index: dict[int, dict[str, Any]],
    today: date,
    tz: tzinfo,
) -> StreakResult:
    """Compute the current and longest workout streak.

    Walks the manifest index, projects each ``starts`` into the
    user-local date, and folds the set into consecutive-day runs.

    The current streak is the run that ends at ``today`` OR ``today-1``;
    any older trailing run yields ``current=0``. The longest streak is
    the maximum run anywhere in the history, regardless of how recent.

    Empty / unparseable inputs produce ``StreakResult()`` — all zeros,
    no dates. Sensors should treat that as the legitimate "no workouts
    yet" state rather than "unavailable".
    """
    dates = set()
    for entry in workouts_index.values():
        d = _parse_local_date(entry.get("starts"), tz)
        if d is not None:
            dates.add(d)

    if not dates:
        return StreakResult()

    sorted_dates = sorted(dates)

    # Longest streak — single linear scan over the sorted set.
    longest = 1
    run = 1
    # ``strict=True`` would fail on the one-date case (the second iterable
    # is empty, so no pairs — that's the intended outcome, not an error).
    for prev, cur in zip(sorted_dates, sorted_dates[1:], strict=False):
        if cur - prev == timedelta(days=1):
            run += 1
            if run > longest:
                longest = run
        else:
            run = 1

    last_date = sorted_dates[-1]
    gap = (today - last_date).days

    # Streak broken: most recent workout is older than yesterday.
    if gap > 1:
        return StreakResult(
            current=0,
            longest=longest,
            current_start=None,
            last_workout_date=last_date,
        )

    # Walk backward from ``last_date`` while the day before is also a streak day.
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
