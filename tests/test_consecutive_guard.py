"""Tier-1 unit tests for ``ConsecutiveLimitGuard``.

The guard wraps the back-to-back-429 bail-out pattern that both backfill
loops (``async_backfill_recent`` and ``async_full_backfill``) need. The
pattern shipped twice in two months — once for each loop — before the
extraction; these tests pin the contract so the next drift bites
immediately.
"""

from __future__ import annotations

import pytest
from rate_limit_budget import ConsecutiveLimitGuard  # type: ignore[import-not-found]


class TestDefaults:
    def test_default_threshold_is_three(self) -> None:
        """0.7.5 + 0.7.14 both arrived at strike count 3 independently — pin it."""
        assert ConsecutiveLimitGuard().threshold == 3

    def test_starts_with_zero_strikes(self) -> None:
        assert ConsecutiveLimitGuard().strikes == 0


class TestRecordFailure:
    def test_first_429_does_not_bail(self) -> None:
        guard = ConsecutiveLimitGuard()
        assert guard.record_failure(429) is False
        assert guard.strikes == 1

    def test_two_consecutive_429s_do_not_bail_with_default_threshold(self) -> None:
        guard = ConsecutiveLimitGuard()
        assert guard.record_failure(429) is False
        assert guard.record_failure(429) is False
        assert guard.strikes == 2

    def test_third_consecutive_429_triggers_bail(self) -> None:
        guard = ConsecutiveLimitGuard()
        guard.record_failure(429)
        guard.record_failure(429)
        assert guard.record_failure(429) is True

    def test_non_429_failure_resets_strike_counter(self) -> None:
        """Sporadic 5xx errors don't count toward the rate-limit threshold."""
        guard = ConsecutiveLimitGuard()
        guard.record_failure(429)
        guard.record_failure(429)
        guard.record_failure(500)
        assert guard.strikes == 0
        # Two fresh 429s after the reset must NOT bail.
        assert guard.record_failure(429) is False
        assert guard.record_failure(429) is False

    def test_none_status_code_resets_counter(self) -> None:
        """Network errors (no HTTP status at all) also reset."""
        guard = ConsecutiveLimitGuard()
        guard.record_failure(429)
        guard.record_failure(None)
        assert guard.strikes == 0

    @pytest.mark.parametrize("status", [200, 204, 403, 404, 500, 502])
    def test_any_non_429_status_resets(self, status: int) -> None:
        guard = ConsecutiveLimitGuard()
        guard.record_failure(429)
        guard.record_failure(429)
        guard.record_failure(status)
        assert guard.strikes == 0


class TestRecordSuccess:
    def test_clean_call_resets_strike_counter(self) -> None:
        guard = ConsecutiveLimitGuard()
        guard.record_failure(429)
        guard.record_failure(429)
        guard.record_success()
        assert guard.strikes == 0
        # After the success, the next 429 starts a fresh streak.
        assert guard.record_failure(429) is False
        assert guard.record_failure(429) is False


class TestCustomThreshold:
    def test_custom_threshold_changes_bail_point(self) -> None:
        guard = ConsecutiveLimitGuard(threshold=2)
        assert guard.record_failure(429) is False
        assert guard.record_failure(429) is True

    def test_threshold_one_bails_immediately(self) -> None:
        guard = ConsecutiveLimitGuard(threshold=1)
        assert guard.record_failure(429) is True
