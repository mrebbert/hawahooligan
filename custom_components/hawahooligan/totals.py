"""Lifetime workout-totals accumulator.

Pure module — no Home Assistant imports — so it's trivially importable in
Tier-1 unit tests via the same ``importlib`` trick the FIT parser uses.

The accumulator tracks each workout's contribution to the totals **once**,
keyed by ``workout_id``. Re-observing the same workout (e.g. a backfill
running on top of an already-seen ride, or a service-driven re-render)
doesn't double-count. Totals survive restarts via the serialization
helpers — the coordinator uses HA's ``Store`` to persist them per entry.

Indoor / outdoor split (added 2026-06-09): every contribution can carry an
``indoor`` flag that gets stored alongside the numeric fields. ``sum`` can
then filter on it so the headline sensors can expose ``outdoor`` /
``indoor`` sub-totals as attributes. Workouts persisted before the flag
existed read back without it and are excluded from both subsets — neither
``indoor`` nor ``outdoor`` claims them — which preserves the overall total
while keeping the splits accurate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Persisted document layout. The on-disk schema is forward-compatible: a
# missing ``indoor`` key in an entry is just treated as "unknown" so older
# payloads load without a migration step.
SCHEMA_VERSION = 1

# Numeric fields we accumulate. ``None`` entries on a workout default to 0 —
# Wahoo omits fields per workout type (indoor rides have no distance, etc.).
_FIELDS = (
    "distance_km",
    "ascent_m",
    "duration_min",
    "calories_kcal",
    "work_kj",
    "tss",
)
_INDOOR_KEY = "indoor"


@dataclass(slots=True)
class WorkoutContribution:
    """The per-workout values that feed the lifetime totals."""

    workout_id: int
    indoor: bool | None = None
    distance_km: float | None = None
    ascent_m: float | None = None
    duration_min: float | None = None
    calories_kcal: float | None = None
    work_kj: float | None = None
    tss: float | None = None


@dataclass(slots=True)
class LifetimeTotals:
    """Idempotent accumulator over a sliding ``workout_id`` set.

    Adding the same ``workout_id`` twice is a no-op — the second call sees the
    id already in the seen-set and returns without touching the sums.
    """

    workouts: dict[int, dict[str, Any]] = field(default_factory=dict)

    def add(self, contribution: WorkoutContribution) -> bool:
        """Record ``contribution`` if not seen before. Returns ``True`` if added."""
        if contribution.workout_id in self.workouts:
            return False
        entry: dict[str, Any] = {}
        for field_name in _FIELDS:
            value = getattr(contribution, field_name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                entry[field_name] = float(value)
        if contribution.indoor is not None:
            entry[_INDOOR_KEY] = bool(contribution.indoor)
        self.workouts[contribution.workout_id] = entry
        return True

    @property
    def workout_count(self) -> int:
        return len(self.workouts)

    @property
    def workout_count_outdoor(self) -> int:
        return sum(1 for e in self.workouts.values() if e.get(_INDOOR_KEY) is False)

    @property
    def workout_count_indoor(self) -> int:
        return sum(1 for e in self.workouts.values() if e.get(_INDOOR_KEY) is True)

    def sum(self, field_name: str, *, indoor: bool | None = None) -> float:
        """Sum ``field_name`` across all entries (default) or one location bucket.

        ``indoor=True`` restricts the sum to entries explicitly tagged as
        indoor; ``indoor=False`` restricts to outdoor. Entries persisted
        before the indoor flag existed have no tag and stay out of both
        subsets — they only contribute to the unfiltered total.
        """
        if field_name not in _FIELDS:
            raise KeyError(f"Unknown lifetime field {field_name!r}")
        total = 0.0
        for entry in self.workouts.values():
            if indoor is True and entry.get(_INDOOR_KEY) is not True:
                continue
            if indoor is False and entry.get(_INDOOR_KEY) is not False:
                continue
            value = entry.get(field_name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total += float(value)
        return total

    @property
    def distance_km(self) -> float:
        return self.sum("distance_km")

    @property
    def ascent_m(self) -> float:
        return self.sum("ascent_m")

    @property
    def duration_min(self) -> float:
        return self.sum("duration_min")

    @property
    def calories_kcal(self) -> float:
        return self.sum("calories_kcal")

    @property
    def work_kj(self) -> float:
        return self.sum("work_kj")

    @property
    def tss(self) -> float:
        return self.sum("tss")

    def as_storage(self) -> dict[str, Any]:
        """Return a JSON-serializable payload for ``Store.async_save``."""
        return {
            "version": SCHEMA_VERSION,
            "workouts": {str(wid): values for wid, values in self.workouts.items()},
        }

    @classmethod
    def from_storage(cls, payload: dict[str, Any] | None) -> LifetimeTotals:
        """Rehydrate from a payload previously returned by :meth:`as_storage`.

        Unknown / missing payloads yield an empty accumulator — this is also
        the first-setup case before anything has been saved.
        """
        if not payload or not isinstance(payload, dict):
            return cls()
        raw = payload.get("workouts") or {}
        if not isinstance(raw, dict):
            return cls()
        out: dict[int, dict[str, Any]] = {}
        for key, values in raw.items():
            try:
                workout_id = int(key)
            except (TypeError, ValueError):
                continue
            if not isinstance(values, dict):
                continue
            entry: dict[str, Any] = {}
            for field_name in _FIELDS:
                value = values.get(field_name)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    entry[field_name] = float(value)
            indoor_value = values.get(_INDOOR_KEY)
            if isinstance(indoor_value, bool):
                entry[_INDOOR_KEY] = indoor_value
            out[workout_id] = entry
        return cls(workouts=out)
