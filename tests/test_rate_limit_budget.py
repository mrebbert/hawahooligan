"""Tier-1 unit tests for ``RateLimitBudget``."""

from __future__ import annotations

import asyncio
import time

import pytest
from rate_limit_budget import RateLimitBudget  # type: ignore[import-not-found]


@pytest.mark.asyncio
async def test_under_budget_calls_return_immediately() -> None:
    budget = RateLimitBudget(max_calls=3, window_seconds=10.0)
    start = time.monotonic()
    for _ in range(3):
        await budget.acquire()
    assert time.monotonic() - start < 0.1


@pytest.mark.asyncio
async def test_over_budget_blocks_until_window_slides(monkeypatch) -> None:
    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        # Advance the simulated clock so the budget sees the window slide.
        nonlocal_now[0] += delay

    nonlocal_now = [0.0]

    def _fake_monotonic() -> float:
        return nonlocal_now[0]

    monkeypatch.setattr("rate_limit_budget.asyncio.sleep", _fake_sleep, raising=True)
    monkeypatch.setattr("rate_limit_budget.time.monotonic", _fake_monotonic, raising=True)

    budget = RateLimitBudget(max_calls=2, window_seconds=10.0)
    await budget.acquire()  # t=0
    nonlocal_now[0] = 1.0
    await budget.acquire()  # t=1
    nonlocal_now[0] = 2.0
    await budget.acquire()  # t=2 — over budget, must sleep

    # The third acquire should have slept long enough for the t=0 entry to
    # fall out of the window — that's ``window_seconds - (now - oldest) + 0.5``
    # = ``10 - (2 - 0) + 0.5`` = ``8.5``.
    assert sleeps, "expected at least one sleep"
    assert sleeps[0] == pytest.approx(8.5)


@pytest.mark.asyncio
async def test_minimum_sleep_is_one_second(monkeypatch) -> None:
    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        nonlocal_now[0] += delay

    nonlocal_now = [0.0]

    def _fake_monotonic() -> float:
        return nonlocal_now[0]

    monkeypatch.setattr("rate_limit_budget.asyncio.sleep", _fake_sleep, raising=True)
    monkeypatch.setattr("rate_limit_budget.time.monotonic", _fake_monotonic, raising=True)

    budget = RateLimitBudget(max_calls=1, window_seconds=10.0)
    await budget.acquire()
    # Bump the clock so the natural wait would be very small (<1 s).
    nonlocal_now[0] = 9.6
    await budget.acquire()
    assert sleeps[0] >= 1.0


@pytest.mark.asyncio
async def test_window_expiry_releases_quota() -> None:
    budget = RateLimitBudget(max_calls=2, window_seconds=0.05)
    await budget.acquire()
    await budget.acquire()
    # Real sleep — short enough to keep the test fast.
    await asyncio.sleep(0.1)
    start = time.monotonic()
    await budget.acquire()
    assert time.monotonic() - start < 0.05
