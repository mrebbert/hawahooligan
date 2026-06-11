"""Rate-limit helpers for the backfill loops.

Pure Python, no Home Assistant imports — Tier-1 testable. Two
complementary primitives:

* :class:`RateLimitBudget` is the *positive* side: it paces outbound
  calls against a rolling window so we don't trip the 5-minute cap in
  the first place.
* :class:`ConsecutiveLimitGuard` is the *negative* side: it counts
  back-to-back 429s and tells the caller when to bail. The 5-min budget
  can't see Wahoo's hourly / daily caps, so an exhausted account just
  keeps 429-ing every detail call until the day resets — the guard
  stops the loop before it floods Wahoo with hopeless requests.

Both have shipped as patterns scattered across the coordinator;
consolidating them here keeps the two backfill loops
(``async_backfill_recent``, ``async_full_backfill``) honest with each
other — a fix to the bail-out shape only needs to land once.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

_LOGGER = logging.getLogger(__name__)


class RateLimitBudget:
    """Rolling-window throttle.

    ``acquire`` blocks until fewer than ``max_calls`` entries fall within the
    last ``window_seconds`` seconds, then records the new call's timestamp.
    """

    __slots__ = ("_calls", "_max_calls", "_window_seconds")

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self._max_calls = max_calls
        self._window_seconds = window_seconds
        self._calls: deque[float] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._calls and self._calls[0] < cutoff:
            self._calls.popleft()

    async def acquire(self) -> None:
        while True:
            now = time.monotonic()
            self._prune(now)
            if len(self._calls) < self._max_calls:
                self._calls.append(now)
                return
            wait = self._window_seconds - (now - self._calls[0]) + 0.5
            _LOGGER.debug(
                "Rate-limit budget exhausted (%d in window), sleeping %.1fs",
                len(self._calls),
                wait,
            )
            await asyncio.sleep(max(wait, 1.0))


class ConsecutiveLimitGuard:
    """Tracks back-to-back 429 hits and signals when to bail.

    Wahoo's Sandbox tier enforces three caps (25 / 5-min, 100 / hour,
    250 / day). The :class:`RateLimitBudget` paces against the 5-min
    cap; this guard is the safety net for the larger windows — once
    Wahoo starts 429-ing every detail call back, the loop should stop
    burning quota that hasn't come back yet.

    ``threshold`` defaults to 3 because that's the strike count both
    ``async_backfill_recent`` (0.7.5) and ``async_full_backfill`` (0.7.14)
    landed on through independent live-debug rounds — keeping the
    default stable means existing tests + production logs still apply.
    """

    __slots__ = ("_strikes", "_threshold")

    def __init__(self, threshold: int = 3) -> None:
        self._strikes = 0
        self._threshold = threshold

    @property
    def threshold(self) -> int:
        """Strike count at which :meth:`record_failure` flips to ``True``."""
        return self._threshold

    @property
    def strikes(self) -> int:
        """Current consecutive 429 count — useful for log lines."""
        return self._strikes

    def record_failure(self, status_code: int | None) -> bool:
        """Note an API failure; return ``True`` when the loop should break.

        Non-429 failures reset the strike counter — they're an isolated
        hiccup, not the rate-limit shape.
        """
        if status_code != 429:
            self._strikes = 0
            return False
        self._strikes += 1
        return self._strikes >= self._threshold

    def record_success(self) -> None:
        """A clean call resets the strike counter."""
        self._strikes = 0
