"""Rolling-window rate-limit budget for the full-history backfill.

Pure Python, no Home Assistant imports — Tier-1 testable.

Wahoo's Sandbox tier caps detail calls at 25 per 5-minute window. The
integration defaults to a budget of 20 per 300 s window so the regular
15-minute poll has room to slip through alongside a long-running
backfill.
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
