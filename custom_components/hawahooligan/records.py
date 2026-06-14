"""Personal-record detection. Indoor and outdoor classes are scored independently."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_TRACKED_METRICS: tuple[tuple[str, str], ...] = (
    ("distance_km", "distance"),
    ("duration_min", "duration"),
    ("power_avg_w", "power_avg"),
    ("tss", "tss"),
)


@dataclass(slots=True, frozen=True)
class PersonalRecord:
    kind: str
    value: float
    previous_value: float | None
    workout_id: int
    indoor: bool


def detect_personal_records(
    new_workout: Any,
    history: Iterable[Any],
) -> list[PersonalRecord]:
    """Return PRs the new workout sets vs same-class history (matching ``indoor`` flag)."""
    new_id = getattr(new_workout, "workout_id", None)
    if new_id is None:
        return []

    new_indoor = bool(getattr(new_workout, "indoor", False))
    same_class = [
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
        previous_max = max(
            (v for h in same_class if (v := getattr(h, field, None)) is not None),
            default=None,
        )
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
