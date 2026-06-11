"""Regression: HA setup completes even when Wahoo API hangs (rate-limited).

A user reported HA restart hanging for minutes when their Sandbox quota
was exhausted. Root cause: ``WahooApi._request`` honours
``Retry-After`` and sleeps up to 300 s on a 429 before retrying once.
With two coordinators (workout + power-zones) called in series during
``async_setup_entry``, that's up to 10 minutes of setup hang.

The fix wraps both first-refresh calls in a 30-second
``asyncio.timeout``; on timeout we log a warning and continue with the
locally cached state (lifetime totals + picker manifest). This test
pins the cap by mocking the workout coordinator's update to a 60-second
sleep and asserting setup completes well below that.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN

from ._setup import oauth_implementation_patches


async def _slow_update_data(*_args, **_kwargs):
    """Stand-in for a rate-limited Wahoo response — would sleep >> timeout."""
    await asyncio.sleep(30)


async def test_setup_does_not_hang_when_workout_refresh_is_slow(
    hass: HomeAssistant,
) -> None:
    """Setup must abandon a stuck first refresh within the configured cap.

    Without the timeout, ``async_config_entry_first_refresh`` would await
    the slow ``_async_update_data`` for the full sleep duration — and on
    a real rate-limited account the equivalent wait reaches 300 s. The
    test patches the timeout constant down to 1 second to keep the test
    cheap; the production default (30 s) is exercised by the prod
    config path, not by this test.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="setup-no-hang-probe",
    )
    entry.add_to_hass(hass)

    started = time.monotonic()

    with (
        # Cut the production 30 s cap to 1 s so the test doesn't burn
        # cycles waiting for a real timeout.
        patch(
            "custom_components.hawahooligan._FIRST_REFRESH_TIMEOUT_SECONDS",
            1,
        ),
        oauth_implementation_patches(),
        patch("custom_components.hawahooligan.WahooApi", return_value=MagicMock()),
        patch(
            "custom_components.hawahooligan.WahooCoordinator._async_update_data",
            new=_slow_update_data,
        ),
        # Power-zones coordinator stays out of the way for this test —
        # the workout coordinator's timeout is the load-bearing assertion.
        patch(
            "custom_components.hawahooligan.WahooPowerZonesCoordinator.async_config_entry_first_refresh",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.hawahooligan.WahooCoordinator.async_backfill_recent",
            new=AsyncMock(return_value=0),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)

    elapsed = time.monotonic() - started
    # 1 s timeout + generous margin for HA's setup overhead. A real
    # hang would be ≥ 30 s here (and up to 300 s in production without
    # the fix).
    assert elapsed < 10, (
        f"setup took {elapsed:.1f}s — the rate-limit first-refresh timeout didn't fire."
    )


async def test_setup_completes_normally_when_api_is_healthy(
    hass: HomeAssistant,
) -> None:
    """Negative regression: a healthy API still gets to populate first.

    The timeout only fires when the refresh hangs. Pin that a fast,
    successful refresh still happens within the setup chain (not deferred
    to the next 15-min poll).
    """
    from custom_components.hawahooligan.coordinator import WorkoutData

    update_calls: list[None] = []

    async def _fast_update(*_args, **_kwargs) -> WorkoutData:
        update_calls.append(None)
        return WorkoutData(workout_id=42)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="setup-healthy-probe",
    )
    entry.add_to_hass(hass)

    with (
        oauth_implementation_patches(),
        patch("custom_components.hawahooligan.WahooApi", return_value=MagicMock()),
        patch(
            "custom_components.hawahooligan.WahooCoordinator._async_update_data",
            new=_fast_update,
        ),
        patch(
            "custom_components.hawahooligan.WahooPowerZonesCoordinator.async_config_entry_first_refresh",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.hawahooligan.WahooCoordinator.async_backfill_recent",
            new=AsyncMock(return_value=0),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)

    assert update_calls, (
        "first refresh never ran on a healthy API — did the timeout swallow "
        "the successful path too?"
    )
