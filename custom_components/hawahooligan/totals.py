"""Lifetime workout-totals accumulator.

Pure module — no Home Assistant imports — so it's trivially importable in
Tier-1 unit tests via the same ``importlib`` trick the FIT parser uses.

The accumulator tracks each workout's contribution to the totals **once**,
keyed by ``workout_id``. Re-observing the same workout (e.g. a backfill
running on top of an already-seen ride, or a service-driven re-render)
doesn't double-count. Totals survive restarts via the serialization
helpers — the coordinator uses HA's ``Store`` to persist them per entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Persisted document layout. Bump :data:`SCHEMA_VERSION` when we change the
# shape so the storage helper can migrate cleanly.
SCHEMA_VERSION = 1

# Fields we accumulate. ``None`` entries on a workout default to 0 — Wahoo
# omits fields per workout type (indoor rides have no distance, etc.).
_FIELDS = (
    "distance_km",
    "ascent_m",
    "duration_min",
    "calories_kcal",
    "work_kj",
    "tss",
)


@dataclass(slots=True)
class WorkoutContribution:
    """The per-workout values that feed the lifetime totals."""

    workout_id: int
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

    workouts: dict[int, dict[str, float]] = field(default_factory=dict)

    def add(self, contribution: WorkoutContribution) -> bool:
        """Record ``contribution`` if not seen before. Returns ``True`` if added."""
        if contribution.workout_id in self.workouts:
            return False
        entry: dict[str, float] = {}
        for field_name in _FIELDS:
            value = getattr(contribution, field_name)
            if isinstance(value, (int, float)):
                entry[field_name] = float(value)
        self.workouts[contribution.workout_id] = entry
        return True

    @property
    def workout_count(self) -> int:
        return len(self.workouts)

    def sum(self, field_name: str) -> float:
        if field_name not in _FIELDS:
            raise KeyError(f"Unknown lifetime field {field_name!r}")
        return sum(entry.get(field_name, 0.0) for entry in self.workouts.values())

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
        out: dict[int, dict[str, float]] = {}
        for key, values in raw.items():
            try:
                workout_id = int(key)
            except (TypeError, ValueError):
                continue
            if not isinstance(values, dict):
                continue
            entry: dict[str, float] = {}
            for field_name in _FIELDS:
                value = values.get(field_name)
                if isinstance(value, (int, float)):
                    entry[field_name] = float(value)
            out[workout_id] = entry
        return cls(workouts=out)
