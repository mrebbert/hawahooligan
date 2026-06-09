"""Tier-1 unit tests for ``totals.py``."""

from __future__ import annotations

import pytest
from totals import (  # type: ignore[import-not-found]
    SCHEMA_VERSION,
    LifetimeTotals,
    WorkoutContribution,
)


class TestLifetimeTotalsAdd:
    def test_first_add_records_and_returns_true(self) -> None:
        totals = LifetimeTotals()
        added = totals.add(
            WorkoutContribution(
                workout_id=42,
                distance_km=25.0,
                ascent_m=300.0,
                duration_min=60.0,
                calories_kcal=600.0,
                work_kj=720.0,
                tss=55.0,
            )
        )
        assert added is True
        assert totals.workout_count == 1
        assert totals.distance_km == pytest.approx(25.0)
        assert totals.ascent_m == pytest.approx(300.0)
        assert totals.duration_min == pytest.approx(60.0)
        assert totals.calories_kcal == pytest.approx(600.0)
        assert totals.work_kj == pytest.approx(720.0)
        assert totals.tss == pytest.approx(55.0)

    def test_re_adding_same_id_is_noop(self) -> None:
        totals = LifetimeTotals()
        totals.add(WorkoutContribution(workout_id=1, distance_km=10.0))
        added_again = totals.add(WorkoutContribution(workout_id=1, distance_km=999.0))
        assert added_again is False
        assert totals.distance_km == pytest.approx(10.0)

    def test_multiple_workouts_sum_correctly(self) -> None:
        totals = LifetimeTotals()
        for workout_id, distance in ((1, 10.0), (2, 20.0), (3, 5.5)):
            totals.add(WorkoutContribution(workout_id=workout_id, distance_km=distance))
        assert totals.workout_count == 3
        assert totals.distance_km == pytest.approx(35.5)

    def test_none_values_skipped(self) -> None:
        totals = LifetimeTotals()
        totals.add(WorkoutContribution(workout_id=1, distance_km=None, ascent_m=100.0))
        assert totals.distance_km == pytest.approx(0.0)
        assert totals.ascent_m == pytest.approx(100.0)


class TestLifetimeTotalsStorage:
    def test_roundtrip(self) -> None:
        totals = LifetimeTotals()
        totals.add(WorkoutContribution(workout_id=10, distance_km=10.0, tss=20.0))
        totals.add(WorkoutContribution(workout_id=11, distance_km=5.0))

        payload = totals.as_storage()
        assert payload["version"] == SCHEMA_VERSION
        assert set(payload["workouts"]) == {"10", "11"}

        restored = LifetimeTotals.from_storage(payload)
        assert restored.workout_count == 2
        assert restored.distance_km == pytest.approx(15.0)
        assert restored.tss == pytest.approx(20.0)
        # Once restored, re-adding the same ids is still a no-op.
        added_again = restored.add(WorkoutContribution(workout_id=10, distance_km=999.0))
        assert added_again is False
        assert restored.distance_km == pytest.approx(15.0)

    def test_empty_payload_yields_empty_totals(self) -> None:
        assert LifetimeTotals.from_storage(None).workout_count == 0
        assert LifetimeTotals.from_storage({}).workout_count == 0

    def test_malformed_payload_is_tolerated(self) -> None:
        totals = LifetimeTotals.from_storage(
            {"workouts": {"not-an-int": {"distance_km": 10.0}, "5": "garbage"}}
        )
        assert totals.workout_count == 0


class TestIndoorOutdoorSplit:
    def test_indoor_flag_stored_per_entry(self) -> None:
        totals = LifetimeTotals()
        totals.add(WorkoutContribution(workout_id=1, indoor=False, distance_km=20.0))
        totals.add(WorkoutContribution(workout_id=2, indoor=True, distance_km=15.0))
        totals.add(WorkoutContribution(workout_id=3, indoor=None, distance_km=5.0))

        assert totals.distance_km == pytest.approx(40.0)
        assert totals.sum("distance_km", indoor=False) == pytest.approx(20.0)
        assert totals.sum("distance_km", indoor=True) == pytest.approx(15.0)

    def test_workout_count_splits(self) -> None:
        totals = LifetimeTotals()
        totals.add(WorkoutContribution(workout_id=1, indoor=False))
        totals.add(WorkoutContribution(workout_id=2, indoor=False))
        totals.add(WorkoutContribution(workout_id=3, indoor=True))
        totals.add(WorkoutContribution(workout_id=4, indoor=None))

        assert totals.workout_count == 4
        assert totals.workout_count_outdoor == 2
        assert totals.workout_count_indoor == 1

    def test_split_survives_storage_roundtrip(self) -> None:
        totals = LifetimeTotals()
        totals.add(WorkoutContribution(workout_id=10, indoor=False, distance_km=42.0))
        totals.add(WorkoutContribution(workout_id=11, indoor=True, distance_km=18.0))
        restored = LifetimeTotals.from_storage(totals.as_storage())

        assert restored.sum("distance_km", indoor=False) == pytest.approx(42.0)
        assert restored.sum("distance_km", indoor=True) == pytest.approx(18.0)
        assert restored.workout_count_outdoor == 1
        assert restored.workout_count_indoor == 1

    def test_legacy_payload_without_indoor_excluded_from_splits(self) -> None:
        # Mimic data written by an older HAWahooligan version: no ``indoor``
        # key on any entry. The headline total still counts them, but
        # neither split claims them.
        legacy_payload = {
            "version": 1,
            "workouts": {
                "1": {"distance_km": 10.0},
                "2": {"distance_km": 20.0},
            },
        }
        totals = LifetimeTotals.from_storage(legacy_payload)

        assert totals.distance_km == pytest.approx(30.0)
        assert totals.workout_count == 2
        assert totals.sum("distance_km", indoor=False) == pytest.approx(0.0)
        assert totals.sum("distance_km", indoor=True) == pytest.approx(0.0)
        assert totals.workout_count_outdoor == 0
        assert totals.workout_count_indoor == 0
