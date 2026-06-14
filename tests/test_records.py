"""Tier-1 unit tests for ``records.py`` (PR detection)."""

from __future__ import annotations

from dataclasses import dataclass

from records import (  # type: ignore[import-not-found]
    PersonalRecord,
    detect_personal_records,
)


@dataclass
class _W:
    """Mimic the minimum surface of ``coordinator.WorkoutData``."""

    workout_id: int | None = None
    indoor: bool = False
    distance_km: float | None = None
    duration_min: float | None = None
    power_avg_w: float | None = None
    tss: float | None = None


class TestDetectPersonalRecords:
    def test_no_workout_id_returns_empty(self) -> None:
        """Anonymous workouts (e.g. cache-fill probes) get no events."""
        assert detect_personal_records(_W(distance_km=10.0), history=[]) == []

    def test_first_ever_workout_is_a_PR_for_every_populated_metric(self) -> None:
        """Per design decision (no warmup) the first workout fires events."""
        new = _W(workout_id=1, distance_km=42.0, duration_min=120.0, tss=80.0)
        records = detect_personal_records(new, history=[])
        kinds = {r.kind for r in records}
        # power_avg_w was None on the new workout — skipped.
        assert kinds == {"distance", "duration", "tss"}
        for r in records:
            assert r.previous_value is None
            assert r.workout_id == 1
            assert r.indoor is False

    def test_workout_with_no_metrics_returns_empty(self) -> None:
        """A summary-less indoor session shouldn't fire phantom events."""
        new = _W(workout_id=1, indoor=True)
        records = detect_personal_records(new, history=[])
        assert records == []

    def test_distance_pr_only_when_strictly_greater(self) -> None:
        """Tying a record is NOT a PR — strict >."""
        history = [_W(workout_id=10, distance_km=50.0)]
        # Equal: no PR.
        records = detect_personal_records(_W(workout_id=11, distance_km=50.0), history)
        assert all(r.kind != "distance" for r in records)
        # Greater: PR.
        records = detect_personal_records(_W(workout_id=12, distance_km=50.1), history)
        assert any(r.kind == "distance" and r.value == 50.1 for r in records)

    def test_previous_value_carries_the_old_max(self) -> None:
        history = [_W(workout_id=1, distance_km=10.0), _W(workout_id=2, distance_km=20.0)]
        records = detect_personal_records(_W(workout_id=3, distance_km=30.0), history)
        distance_pr = next(r for r in records if r.kind == "distance")
        assert distance_pr.previous_value == 20.0  # the higher of 10 and 20
        assert distance_pr.value == 30.0

    def test_indoor_and_outdoor_records_are_tracked_separately(self) -> None:
        """A treadmill 5K beats no outdoor 5K records and vice versa."""
        history = [
            _W(workout_id=1, indoor=False, distance_km=100.0),  # outdoor record
            _W(workout_id=2, indoor=True, distance_km=20.0),  # indoor max
        ]
        # New indoor 25km beats the indoor 20 → PR for indoor.
        new_indoor = _W(workout_id=3, indoor=True, distance_km=25.0)
        records = detect_personal_records(new_indoor, history)
        distance_pr = next(r for r in records if r.kind == "distance")
        assert distance_pr.previous_value == 20.0  # NOT 100.0 (which is outdoor)
        assert distance_pr.indoor is True

        # New outdoor 50km does NOT beat outdoor 100 → no PR.
        new_outdoor = _W(workout_id=4, indoor=False, distance_km=50.0)
        records = detect_personal_records(new_outdoor, history)
        assert all(r.kind != "distance" for r in records)

    def test_history_entries_missing_a_metric_are_ignored_for_that_metric(self) -> None:
        """Indoor trainer rides with distance_km=None mustn't reset the indoor distance bar."""
        history = [
            _W(workout_id=1, indoor=True, distance_km=None, duration_min=60.0),
            _W(workout_id=2, indoor=True, distance_km=12.0, duration_min=45.0),
        ]
        # New indoor 13km → beats 12 → distance PR. duration 50 → does NOT
        # beat 60 → no duration PR.
        new = _W(workout_id=3, indoor=True, distance_km=13.0, duration_min=50.0)
        records = detect_personal_records(new, history)
        kinds = {r.kind for r in records}
        assert "distance" in kinds
        assert "duration" not in kinds

    def test_new_workout_id_excluded_from_history_comparison(self) -> None:
        """Defensive: if the caller leaks the new workout into history, still works.

        The contract says callers exclude it, but if they don't (e.g. a
        re-entrant cache write race), we self-defend by id-comparison.
        """
        history = [_W(workout_id=5, distance_km=50.0)]  # this IS the new workout
        new = _W(workout_id=5, distance_km=50.0)  # same id, same value
        records = detect_personal_records(new, history)
        # Without the id filter we'd be comparing 50 vs 50 → no PR.
        # With the id filter, history shrinks to empty → 50 IS a PR.
        # The contract: id-of-new-workout is filtered out of history.
        distance_pr = next(r for r in records if r.kind == "distance")
        assert distance_pr.previous_value is None

    def test_multiple_PRs_in_a_single_workout_all_fire(self) -> None:
        """A breakthrough century ride can beat distance + duration + TSS at once."""
        history = [
            _W(workout_id=1, distance_km=50.0, duration_min=120.0, tss=80.0, power_avg_w=200.0)
        ]
        new = _W(workout_id=2, distance_km=120.0, duration_min=300.0, tss=200.0, power_avg_w=220.0)
        records = detect_personal_records(new, history)
        kinds = {r.kind for r in records}
        assert kinds == {"distance", "duration", "tss", "power_avg"}

    def test_record_carries_workout_id_for_traceability(self) -> None:
        new = _W(workout_id=4242, distance_km=99.0)
        records = detect_personal_records(new, history=[])
        assert records[0].workout_id == 4242

    def test_PersonalRecord_is_frozen_so_listeners_cant_mutate(self) -> None:
        import dataclasses

        r = PersonalRecord(
            kind="distance", value=1.0, previous_value=None, workout_id=1, indoor=False
        )
        # frozen=True dataclasses raise FrozenInstanceError on assignment.
        try:
            r.value = 2.0  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            return
        raise AssertionError(
            "PersonalRecord should be frozen — listeners must not be able to mutate it"
        )
