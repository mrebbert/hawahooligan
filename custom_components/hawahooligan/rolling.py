"""Trailing-window totals from the manifest index + detail cache.

Best-effort: workouts without a cached detail entry are skipped so the
output stays self-consistent (counts and sums refer to the same set).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol


class _WorkoutDetail(Protocol):
    indoor: bool
    distance_km: float | None
    duration_min: float | None
    tss: float | None


@dataclass(slots=True)
class RollingTotals:
    workout_count: int = 0
    workout_count_outdoor: int = 0
    workout_count_indoor: int = 0
    distance_km: float = 0.0
    distance_outdoor_km: float = 0.0
    distance_indoor_km: float = 0.0
    duration_min: float = 0.0
    duration_outdoor_min: float = 0.0
    duration_indoor_min: float = 0.0
    tss: float = 0.0


def _parse_starts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_rolling_totals(
    detail_cache: dict[int, _WorkoutDetail],
    workouts_index: dict[int, dict[str, Any]],
    window_days: int,
    now: datetime,
) -> RollingTotals:
    """Sum cached metrics over workouts that started in the trailing window."""
    if window_days <= 0:
        return RollingTotals()

    cutoff = now - timedelta(days=window_days)
    totals = RollingTotals()

    for wid, idx_entry in workouts_index.items():
        starts = _parse_starts(idx_entry.get("starts"))
        if starts is None or starts < cutoff or starts > now:
            continue
        data = detail_cache.get(wid)
        if data is None:
            continue

        is_indoor = bool(getattr(data, "indoor", False))
        totals.workout_count += 1
        if is_indoor:
            totals.workout_count_indoor += 1
        else:
            totals.workout_count_outdoor += 1

        distance = getattr(data, "distance_km", None)
        if distance is not None:
            totals.distance_km += distance
            if is_indoor:
                totals.distance_indoor_km += distance
            else:
                totals.distance_outdoor_km += distance

        duration = getattr(data, "duration_min", None)
        if duration is not None:
            totals.duration_min += duration
            if is_indoor:
                totals.duration_indoor_min += duration
            else:
                totals.duration_outdoor_min += duration

        tss = getattr(data, "tss", None)
        if tss is not None:
            totals.tss += tss

    return totals
