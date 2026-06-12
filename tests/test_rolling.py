"""Tier-1 unit tests for ``rolling.py`` (trailing-window totals)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from rolling import (  # type: ignore[import-not-found]
    RollingTotals,
    compute_rolling_totals,
)


@dataclass
class _Detail:
    """Mimic the minimum surface of ``coordinator.WorkoutData``."""

    indoor: bool = False
    distance_km: float | None = None
    duration_min: float | None = None
    tss: float | None = None


def _index(starts: str, wid: int = 1) -> dict[int, dict[str, Any]]:
    return {wid: {"starts": starts}}


_NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


class TestComputeRollingTotals:
    def test_empty_inputs_return_zeroed_totals(self) -> None:
        result = compute_rolling_totals({}, {}, window_days=7, now=_NOW)
        assert result == RollingTotals()

    def test_zero_window_returns_zeroed_totals(self) -> None:
        """``window_days=0`` is a no-op rather than an off-by-one foot-gun."""
        idx = _index((_NOW - timedelta(hours=1)).isoformat())
        cache = {1: _Detail(distance_km=10.0)}
        assert compute_rolling_totals(cache, idx, 0, _NOW) == RollingTotals()

    def test_workout_inside_window_counts_in(self) -> None:
        idx = _index((_NOW - timedelta(days=3)).isoformat())
        cache = {1: _Detail(distance_km=42.0, duration_min=120.0, tss=85.0)}
        result = compute_rolling_totals(cache, idx, 7, _NOW)
        assert result.workout_count == 1
        assert result.distance_km == pytest.approx(42.0)
        assert result.duration_min == pytest.approx(120.0)
        assert result.tss == pytest.approx(85.0)

    def test_workout_older_than_window_is_excluded(self) -> None:
        idx = _index((_NOW - timedelta(days=8)).isoformat())
        cache = {1: _Detail(distance_km=50.0)}
        result = compute_rolling_totals(cache, idx, 7, _NOW)
        assert result.workout_count == 0
        assert result.distance_km == 0.0

    def test_future_workout_is_excluded(self) -> None:
        """Wahoo can emit scheduled workouts with future ``starts``.

        Including them in "last 7 days" would lie to the user — a
        future Sunday ride doesn't belong in this week's sum yet.
        """
        idx = _index((_NOW + timedelta(hours=2)).isoformat())
        cache = {1: _Detail(distance_km=99.0)}
        result = compute_rolling_totals(cache, idx, 7, _NOW)
        assert result.workout_count == 0

    def test_boundary_at_exact_cutoff_is_included(self) -> None:
        """``starts >= cutoff`` keeps the workout that landed at the boundary."""
        idx = _index((_NOW - timedelta(days=7)).isoformat())
        cache = {1: _Detail(distance_km=10.0)}
        result = compute_rolling_totals(cache, idx, 7, _NOW)
        assert result.workout_count == 1

    def test_workout_with_no_cached_detail_does_not_contribute(self) -> None:
        """A row in the manifest without a cache hit is invisible to sums."""
        idx = _index((_NOW - timedelta(days=1)).isoformat())
        result = compute_rolling_totals({}, idx, 7, _NOW)
        # No partial counting — keeps workout_count consistent with distance.
        assert result.workout_count == 0
        assert result.distance_km == 0.0

    def test_indoor_and_outdoor_split_correctly(self) -> None:
        idx = {
            1: {"starts": (_NOW - timedelta(days=1)).isoformat()},
            2: {"starts": (_NOW - timedelta(days=2)).isoformat()},
            3: {"starts": (_NOW - timedelta(days=3)).isoformat()},
        }
        cache = {
            1: _Detail(indoor=False, distance_km=30.0, duration_min=90.0),
            2: _Detail(indoor=True, distance_km=12.0, duration_min=45.0),
            3: _Detail(indoor=False, distance_km=18.0, duration_min=60.0),
        }
        result = compute_rolling_totals(cache, idx, 7, _NOW)
        assert result.workout_count == 3
        assert result.workout_count_outdoor == 2
        assert result.workout_count_indoor == 1
        assert result.distance_km == pytest.approx(60.0)
        assert result.distance_outdoor_km == pytest.approx(48.0)
        assert result.distance_indoor_km == pytest.approx(12.0)
        assert result.duration_outdoor_min == pytest.approx(150.0)
        assert result.duration_indoor_min == pytest.approx(45.0)

    def test_unparseable_starts_skips_silently(self) -> None:
        idx = {
            1: {"starts": "not an iso date"},
            2: {"starts": (_NOW - timedelta(days=1)).isoformat()},
        }
        cache = {1: _Detail(distance_km=10.0), 2: _Detail(distance_km=20.0)}
        result = compute_rolling_totals(cache, idx, 7, _NOW)
        assert result.workout_count == 1
        assert result.distance_km == pytest.approx(20.0)

    def test_missing_starts_field_skips_silently(self) -> None:
        idx = {1: {}, 2: {"starts": (_NOW - timedelta(days=1)).isoformat()}}
        cache = {1: _Detail(distance_km=10.0), 2: _Detail(distance_km=20.0)}
        result = compute_rolling_totals(cache, idx, 7, _NOW)
        assert result.workout_count == 1

    def test_wahoo_z_suffix_iso_parses(self) -> None:
        """Wahoo emits ISO with the ``Z`` UTC marker — must roundtrip."""
        idx = {1: {"starts": "2026-06-11T08:30:00Z"}}
        cache = {1: _Detail(distance_km=15.0)}
        # _NOW is 2026-06-12 12:00 UTC → 28h ago → inside 7d.
        result = compute_rolling_totals(cache, idx, 7, _NOW)
        assert result.workout_count == 1
        assert result.distance_km == pytest.approx(15.0)

    def test_partial_metrics_only_sum_what_exists(self) -> None:
        """Indoor workouts often have ``distance_km=None`` (trainer rides).

        Counting them but not summing their distance keeps the count and
        the distance independently meaningful — a treadmill run shouldn't
        zero out a real run's distance.
        """
        idx = {
            1: {"starts": (_NOW - timedelta(days=1)).isoformat()},
            2: {"starts": (_NOW - timedelta(days=2)).isoformat()},
        }
        cache = {
            1: _Detail(indoor=True, distance_km=None, duration_min=60.0, tss=70.0),
            2: _Detail(indoor=False, distance_km=25.0, duration_min=80.0, tss=None),
        }
        result = compute_rolling_totals(cache, idx, 7, _NOW)
        assert result.workout_count == 2
        # Distance only carries the outdoor workout; indoor None drops cleanly.
        assert result.distance_km == pytest.approx(25.0)
        assert result.distance_indoor_km == pytest.approx(0.0)
        # Duration sums both; TSS only the one that had it.
        assert result.duration_min == pytest.approx(140.0)
        assert result.tss == pytest.approx(70.0)

    def test_28d_window_aggregates_more_than_7d_window(self) -> None:
        """Sanity: wider window catches strictly more workouts."""
        idx = {
            1: {"starts": (_NOW - timedelta(days=1)).isoformat()},
            2: {"starts": (_NOW - timedelta(days=10)).isoformat()},
            3: {"starts": (_NOW - timedelta(days=20)).isoformat()},
            4: {"starts": (_NOW - timedelta(days=30)).isoformat()},
        }
        cache = {wid: _Detail(distance_km=10.0) for wid in idx}
        r7 = compute_rolling_totals(cache, idx, 7, _NOW)
        r28 = compute_rolling_totals(cache, idx, 28, _NOW)
        assert r7.workout_count == 1
        assert r28.workout_count == 3
        # Day-30 workout falls outside even the 28d window.
        assert r28.workout_count < len(idx)
