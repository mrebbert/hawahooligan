"""``WorkoutData`` dataclass + Wahoo-API → dataclass projection.

Extracted from ``coordinator.py`` to keep that module focused on the
DataUpdateCoordinator wiring. Pure Python; no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .const import is_indoor, workout_type_name
from .manifest import RecentWorkout

_DETAILS_TRANSIENT_FIELDS = frozenset({"recent", "selected_workout_id"})


@dataclass(slots=True)
class WorkoutData:
    """Shape exposed to sensor entities — whichever workout the user is viewing.

    Numeric values are pre-cast to ``float`` and converted to the units the
    sensors advertise (km, km/h, min, …). Wahoo-absent fields stay ``None``.
    """

    workout_id: int | None = None
    name: str | None = None
    starts: str | None = None
    workout_type_id: int | None = None
    workout_type_name: str | None = None
    indoor: bool = False
    manual: bool = False
    edited: bool = False
    time_zone: str | None = None
    fitness_app_id: int | None = None
    file_url: str | None = None
    geojson_url: str | None = None
    route_id: int | None = None
    plan_id: int | None = None
    plan_ids: list[int] = field(default_factory=list)
    # Summary fields (units already applied)
    distance_km: float | None = None
    ascent_m: float | None = None
    duration_min: float | None = None
    duration_total_min: float | None = None
    duration_paused_min: float | None = None
    speed_avg_kmh: float | None = None
    power_avg_w: float | None = None
    power_np_w: float | None = None
    tss: float | None = None
    heart_rate_avg_bpm: float | None = None
    cadence_avg_rpm: float | None = None
    calories_kcal: float | None = None
    work_kj: float | None = None
    # Picker context
    recent: list[RecentWorkout] = field(default_factory=list)
    selected_workout_id: int | None = None


def workout_data_to_storage(data: WorkoutData) -> dict[str, Any]:
    """Strip transient picker context so the cache stays workout-scoped."""
    out = asdict(data)
    for key in _DETAILS_TRANSIENT_FIELDS:
        out.pop(key, None)
    return out


def workout_data_from_storage(payload: dict[str, Any]) -> WorkoutData | None:
    """Rehydrate from cache, filtering unknown fields for forward compat."""
    if not isinstance(payload, dict):
        return None
    known = {f.name for f in fields(WorkoutData)}
    filtered = {k: v for k, v in payload.items() if k in known}
    if not filtered:
        return None
    try:
        return WorkoutData(**filtered)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    """Wahoo summary values come as strings; None / empty mean 'absent'."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_workout_data(workout: dict[str, Any]) -> WorkoutData:
    """Project a Wahoo ``GET /v1/workouts/:id`` response onto ``WorkoutData``."""
    summary = workout.get("workout_summary") or {}
    file_obj = summary.get("file") or {}
    type_id = workout.get("workout_type_id")

    distance_m = _as_float(summary.get("distance_accum"))
    duration_s = _as_float(summary.get("duration_active_accum"))
    duration_total_s = _as_float(summary.get("duration_total_accum"))
    duration_paused_s = _as_float(summary.get("duration_paused_accum"))
    speed_ms = _as_float(summary.get("speed_avg"))
    work_j = _as_float(summary.get("work_accum"))

    plan_ids_raw = workout.get("plan_ids") or []
    plan_ids: list[int] = []
    if isinstance(plan_ids_raw, list):
        for pid in plan_ids_raw:
            try:
                plan_ids.append(int(pid))
            except (TypeError, ValueError):
                continue

    return WorkoutData(
        workout_id=workout.get("id"),
        name=workout.get("name") or summary.get("name"),
        starts=workout.get("starts"),
        workout_type_id=type_id,
        workout_type_name=workout_type_name(type_id),
        indoor=is_indoor(type_id),
        manual=bool(workout.get("manual") or summary.get("manual")),
        edited=bool(workout.get("edited") or summary.get("edited")),
        time_zone=workout.get("time_zone") or summary.get("time_zone"),
        fitness_app_id=workout.get("fitness_app_id"),
        file_url=file_obj.get("url"),
        route_id=workout.get("route_id"),
        plan_id=workout.get("plan_id"),
        plan_ids=plan_ids,
        distance_km=distance_m / 1000.0 if distance_m is not None else None,
        ascent_m=_as_float(summary.get("ascent_accum")),
        duration_min=duration_s / 60.0 if duration_s is not None else None,
        duration_total_min=(duration_total_s / 60.0 if duration_total_s is not None else None),
        duration_paused_min=(duration_paused_s / 60.0 if duration_paused_s is not None else None),
        speed_avg_kmh=speed_ms * 3.6 if speed_ms is not None else None,
        power_avg_w=_as_float(summary.get("power_avg")),
        power_np_w=_as_float(summary.get("power_bike_np_last")),
        tss=_as_float(summary.get("power_bike_tss_last")),
        heart_rate_avg_bpm=_as_float(summary.get("heart_rate_avg")),
        cadence_avg_rpm=_as_float(summary.get("cadence_avg")),
        calories_kcal=_as_float(summary.get("calories_accum")),
        work_kj=work_j / 1000.0 if work_j is not None else None,
    )


def build_recent_from_listing(
    workouts: list[dict[str, Any]],
    directory: Path,
) -> list[RecentWorkout]:
    """Project raw listing entries onto ``RecentWorkout``, sorted desc by ``starts``.

    ``has_track`` is filled from disk so the viewer can distinguish
    renderable rides from indoor / manual sessions.
    """
    result: list[RecentWorkout] = []
    for workout in workouts:
        workout_id = workout.get("id")
        if workout_id is None:
            continue
        type_id = workout.get("workout_type_id")
        summary = workout.get("workout_summary") or {}
        duration_s = _as_float(summary.get("duration_active_accum"))
        result.append(
            RecentWorkout(
                id=workout_id,
                name=workout.get("name") or summary.get("name"),
                starts=workout.get("starts"),
                workout_type_id=type_id,
                workout_type_name=workout_type_name(type_id),
                indoor=is_indoor(type_id),
                manual=bool(workout.get("manual") or summary.get("manual")),
                has_track=(directory / f"{workout_id}.geojson").is_file(),
                duration_min=duration_s / 60.0 if duration_s is not None else None,
            )
        )
    # Listing arrives desc by ``starts`` already — sort defensively in case it drifts.
    result.sort(key=lambda r: r.starts or "", reverse=True)
    return result
