"""Rolling-window totals over the cached workout history.

Pure module — no Home Assistant imports — so it's trivially testable
in Tier-1 via the same ``importlib`` trick the FIT parser uses.

The function takes the coordinator's cached detail map plus the
manifest index and folds workouts whose ``starts`` falls in the
trailing ``window_days`` into a small totals dataclass. Indoor /
outdoor split is carried so cards and templates can show the breakdown
without re-iterating the workouts themselves.

Gaps in the detail cache are silently ignored: the window only sees
workouts the integration has actually fetched. For users who ran
``full_backfill`` this is identical to a true history sum; for cold
starts or rate-limited accounts, it's the best-effort number we can
produce without going back to the API. The contract is documented on
the sensor strings so the dashboard reads as "≥ this" rather than
"exactly this".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol


class _WorkoutDetail(Protocol):
    """Minimum surface ``compute_rolling_totals`` reads from a cache entry.

    Defined as a Protocol so the function is decoupled from
    ``coordinator.WorkoutData`` and the Tier-1 tests can pass in plain
    dataclass fixtures.
    """

    indoor: bool
    distance_km: float | None
    duration_min: float | None
    tss: float | None


@dataclass(slots=True)
class RollingTotals:
    """Trailing-window sums + indoor/outdoor breakdown.

    Workout count is the only integer field; everything else stays
    float so the indoor / outdoor sub-sums can hold per-workout
    fractions without surprises.
    """

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
    """Parse Wahoo's ISO-8601 ``starts`` field.

    Returns ``None`` for missing / unparseable values — the caller
    treats those workouts as outside any window rather than as
    "happened at epoch 0".
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        # Wahoo uses ``Z`` suffix; Python <3.11 needs the substitution.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_rolling_totals(
    detail_cache: dict[int, _WorkoutDetail],
    workouts_index: dict[int, dict[str, Any]],
    window_days: int,
    now: datetime,
) -> RollingTotals:
    """Sum cached metrics over workouts that started in the trailing window.

    Iterates the manifest index (cheap, always present) for the
    ``starts`` timestamps and looks up each entry in the detail cache
    for the numeric fields. Workouts without a cached detail entry
    contribute to neither count nor sums — a deliberate choice so the
    output stays self-consistent (a workout that contributes to
    ``workout_count`` must also be able to contribute to ``distance_km``).
    """
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
