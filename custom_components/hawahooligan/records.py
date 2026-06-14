"""Personal-record detection against the cached workout history.

Pure module — no Home Assistant imports — so it's Tier-1 testable via
the ``importlib`` trick.

Given a freshly-fetched workout + the detail cache of historical
workouts, returns a list of metrics where the new workout sets a new
PR. The four metrics tracked: ``distance_km``, ``duration_min``,
``power_avg_w``, ``tss``. Indoor and outdoor records are kept separate
— a treadmill 5K is not the same record class as an outdoor 5K, and
mixing them would let a single indoor trainer session demolish every
outdoor record.

Per design decision (2026-06-14): NO warmup period. Even the first
workout fires PR events — it sets the baseline and IS the record by
virtue of being the only entry. Backfill flooding is prevented at the
caller layer: PR detection runs only in the polling path, not in the
bulk-backfill path. See ``coordinator.py`` for the wiring rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# The four metrics we treat as PR-worthy. Each entry: ``(field_name,
# pr_kind)`` — ``field_name`` is the attribute on ``WorkoutData``,
# ``pr_kind`` is the string surfaced on the event bus and in
# automations. Kept as a tuple of tuples so additions are explicit
# (and tested against the schema).
_TRACKED_METRICS: tuple[tuple[str, str], ...] = (
    ("distance_km", "distance"),
    ("duration_min", "duration"),
    ("power_avg_w", "power_avg"),
    ("tss", "tss"),
)


@dataclass(slots=True, frozen=True)
class PersonalRecord:
    """A single PR firing.

    ``kind`` is the metric label (e.g. ``"distance"``), ``value`` is
    the new high, ``previous_value`` is what it beat (``None`` for the
    first-ever workout in this class), ``workout_id`` identifies the
    workout that set it, ``indoor`` distinguishes the record class so
    automations can format outdoor / indoor PRs differently.
    """

    kind: str
    value: float
    previous_value: float | None
    workout_id: int
    indoor: bool


def detect_personal_records(
    new_workout: Any,
    history: Iterable[Any],
) -> list[PersonalRecord]:
    """Return the list of PRs the new workout sets.

    Compares the new workout's four tracked metrics against the
    indoor-or-outdoor max of the same class across ``history``.
    Empty list = no PRs (or, equivalently, the workout has none of the
    tracked metrics populated).

    The new workout's ``workout_id`` MUST be excluded from the history
    iterable by the caller — comparing a workout against itself would
    never produce a PR. Coordinator wiring handles this by passing
    ``self._detail_cache.values()`` BEFORE storing the new entry.
    """
    new_id = getattr(new_workout, "workout_id", None)
    if new_id is None:
        return []

    new_indoor = bool(getattr(new_workout, "indoor", False))
    history_filtered = [
        h
        for h in history
        if bool(getattr(h, "indoor", False)) is new_indoor
        and getattr(h, "workout_id", None) != new_id
    ]

    records: list[PersonalRecord] = []
    for field, kind in _TRACKED_METRICS:
        new_value = getattr(new_workout, field, None)
        if new_value is None:
            continue

        previous_max: float | None = None
        for h in history_filtered:
            hv = getattr(h, field, None)
            if hv is None:
                continue
            if previous_max is None or hv > previous_max:
                previous_max = hv

        # Either no history yet (first workout of this class) OR the new
        # value strictly exceeds the previous max → PR.
        if previous_max is None or new_value > previous_max:
            records.append(
                PersonalRecord(
                    kind=kind,
                    value=float(new_value),
                    previous_value=float(previous_max) if previous_max is not None else None,
                    workout_id=int(new_id),
                    indoor=new_indoor,
                )
            )

    return records
