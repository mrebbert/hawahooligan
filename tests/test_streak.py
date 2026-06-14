"""Tier-1 unit tests for ``streak.py``."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from streak import (  # type: ignore[import-not-found]
    StreakResult,
    compute_streak,
)

_BERLIN = ZoneInfo("Europe/Berlin")
_UTC = UTC


def _idx(*starts: str) -> dict[int, dict[str, Any]]:
    """Build a workouts-index-shaped dict from a list of ISO ``starts`` strings."""
    return {i: {"starts": s} for i, s in enumerate(starts)}


def _iso_at(d: date, hour: int = 12, *, tz: Any = _UTC) -> str:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=tz).isoformat()


class TestComputeStreak:
    def test_empty_index_returns_all_zeros(self) -> None:
        result = compute_streak({}, today=date(2026, 6, 14), tz=_BERLIN)
        assert result == StreakResult()

    def test_single_workout_today(self) -> None:
        today = date(2026, 6, 14)
        idx = _idx(_iso_at(today))
        result = compute_streak(idx, today=today, tz=_BERLIN)
        assert result.current == 1
        assert result.longest == 1
        assert result.current_start == today
        assert result.last_workout_date == today

    def test_three_consecutive_days_ending_today(self) -> None:
        today = date(2026, 6, 14)
        idx = _idx(
            _iso_at(today - timedelta(days=2)),
            _iso_at(today - timedelta(days=1)),
            _iso_at(today),
        )
        result = compute_streak(idx, today=today, tz=_BERLIN)
        assert result.current == 3
        assert result.longest == 3
        assert result.current_start == today - timedelta(days=2)

    def test_streak_ending_yesterday_is_still_active(self) -> None:
        """Common user flow: open dashboard in the morning before today's ride."""
        today = date(2026, 6, 14)
        idx = _idx(
            _iso_at(today - timedelta(days=3)),
            _iso_at(today - timedelta(days=2)),
            _iso_at(today - timedelta(days=1)),
        )
        result = compute_streak(idx, today=today, tz=_BERLIN)
        # Yesterday counts as "still on the streak today" — they have hours
        # of the day left to ride.
        assert result.current == 3
        assert result.longest == 3

    def test_streak_ending_two_days_ago_is_broken(self) -> None:
        today = date(2026, 6, 14)
        idx = _idx(
            _iso_at(today - timedelta(days=4)),
            _iso_at(today - timedelta(days=3)),
            _iso_at(today - timedelta(days=2)),
        )
        result = compute_streak(idx, today=today, tz=_BERLIN)
        assert result.current == 0
        # Longest is preserved even after the streak breaks.
        assert result.longest == 3
        assert result.current_start is None
        assert result.last_workout_date == today - timedelta(days=2)

    def test_multiple_workouts_same_day_count_as_one(self) -> None:
        """Indoor recovery + outdoor ride on the same day = still one streak day."""
        today = date(2026, 6, 14)
        idx = _idx(
            _iso_at(today, hour=7),
            _iso_at(today, hour=18),
            _iso_at(today - timedelta(days=1), hour=8),
        )
        result = compute_streak(idx, today=today, tz=_BERLIN)
        assert result.current == 2  # not 3 — same-day extras don't extend

    def test_workout_at_local_midnight_lands_on_correct_local_date(self) -> None:
        """A 00:30 Berlin ride is "today" locally even though UTC says yesterday.

        Wahoo timestamps are TZ-aware (with offset); the projection into
        the user's local TZ must use that offset, not raw UTC.
        """
        today = date(2026, 6, 14)
        # 00:30 Berlin = 22:30 UTC the previous day. We want this to
        # count as "today" (Berlin date).
        starts = datetime(2026, 6, 14, 0, 30, 0, tzinfo=_BERLIN).isoformat()
        idx = {1: {"starts": starts}}
        result = compute_streak(idx, today=today, tz=_BERLIN)
        assert result.current == 1
        assert result.last_workout_date == today

    def test_late_evening_local_workout_does_not_bleed_to_next_local_date(
        self,
    ) -> None:
        """23:30 local = same local day. Sanity check the other boundary."""
        today = date(2026, 6, 14)
        starts = datetime(2026, 6, 14, 23, 30, 0, tzinfo=_BERLIN).isoformat()
        idx = {1: {"starts": starts}}
        result = compute_streak(idx, today=today, tz=_BERLIN)
        assert result.current == 1
        assert result.last_workout_date == today

    def test_wahoo_z_suffix_iso_parses(self) -> None:
        """Wahoo emits ISO with ``Z`` for UTC — must roundtrip."""
        today = date(2026, 6, 14)
        idx = {1: {"starts": "2026-06-14T10:00:00Z"}}
        result = compute_streak(idx, today=today, tz=_UTC)
        assert result.current == 1

    def test_unparseable_starts_is_skipped(self) -> None:
        today = date(2026, 6, 14)
        idx = {
            1: {"starts": "not an iso date"},
            2: {"starts": _iso_at(today)},
        }
        result = compute_streak(idx, today=today, tz=_BERLIN)
        # The bogus row is silently dropped; the valid one still counts.
        assert result.current == 1

    def test_missing_starts_is_skipped(self) -> None:
        today = date(2026, 6, 14)
        idx = {1: {}, 2: {"starts": _iso_at(today)}}
        result = compute_streak(idx, today=today, tz=_BERLIN)
        assert result.current == 1

    def test_longest_streak_can_exceed_current_streak(self) -> None:
        """Old long streak + short current streak = longest != current."""
        today = date(2026, 6, 14)
        # Five-day streak 3 months ago + one workout today.
        old_anchor = today - timedelta(days=90)
        idx = _idx(
            _iso_at(old_anchor),
            _iso_at(old_anchor + timedelta(days=1)),
            _iso_at(old_anchor + timedelta(days=2)),
            _iso_at(old_anchor + timedelta(days=3)),
            _iso_at(old_anchor + timedelta(days=4)),
            _iso_at(today),
        )
        result = compute_streak(idx, today=today, tz=_BERLIN)
        assert result.current == 1
        assert result.longest == 5

    def test_streak_with_gap_in_history(self) -> None:
        """Day 1-3 streak, gap, day 5-6 ending today → current=2, longest=3."""
        today = date(2026, 6, 14)
        idx = _idx(
            _iso_at(today - timedelta(days=5)),
            _iso_at(today - timedelta(days=4)),
            _iso_at(today - timedelta(days=3)),
            # gap on day 2
            _iso_at(today - timedelta(days=1)),
            _iso_at(today),
        )
        result = compute_streak(idx, today=today, tz=_BERLIN)
        assert result.current == 2
        assert result.longest == 3

    def test_current_start_is_first_day_of_run(self) -> None:
        today = date(2026, 6, 14)
        idx = _idx(
            _iso_at(today - timedelta(days=6)),
            _iso_at(today - timedelta(days=5)),
            _iso_at(today - timedelta(days=4)),
            _iso_at(today - timedelta(days=3)),
            _iso_at(today - timedelta(days=2)),
            _iso_at(today - timedelta(days=1)),
            _iso_at(today),
        )
        result = compute_streak(idx, today=today, tz=_BERLIN)
        assert result.current == 7
        assert result.current_start == today - timedelta(days=6)

    def test_one_workout_yesterday_only(self) -> None:
        today = date(2026, 6, 14)
        idx = _idx(_iso_at(today - timedelta(days=1)))
        result = compute_streak(idx, today=today, tz=_BERLIN)
        # Streak of 1 ending yesterday is still active per the yesterday
        # allowance — they can still ride today and extend it.
        assert result.current == 1
        assert result.longest == 1
