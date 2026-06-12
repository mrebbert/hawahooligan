"""Regression: ``hawahooligan.refresh_power_zones`` triggers the zones coordinator.

The power-zones coordinator polls every 24 h, which is way too long
when the user has just updated FTP in the Wahoo app, just walked
through a Reauth that finally granted ``power_zones_read``, or saw
the zones first-refresh time out at the last HA setup.

This test pins the contract: calling the service dispatches a refresh
to the power-zones coordinator (and only that one — the workout
coordinator stays untouched, no extra Wahoo API calls).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="refresh-power-zones-probe",
    )
    entry.add_to_hass(hass)
    with (
        oauth_implementation_patches(),
        patch("custom_components.hawahooligan.WahooApi", return_value=MagicMock()),
        patch(
            "custom_components.hawahooligan.WahooCoordinator._async_update_data",
            new=AsyncMock(return_value=WorkoutData(workout_id=None)),
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
        await hass.async_block_till_done()
    return entry


async def test_refresh_power_zones_dispatches_to_power_zones_coordinator(
    hass: HomeAssistant,
) -> None:
    entry = await _setup_entry(hass)
    power_zones_coordinator = entry.runtime_data.power_zones_coordinator
    workout_coordinator = entry.runtime_data.coordinator

    with (
        patch.object(power_zones_coordinator, "async_refresh", new=AsyncMock()) as power_zones_spy,
        patch.object(workout_coordinator, "async_refresh", new=AsyncMock()) as workout_spy,
    ):
        await hass.services.async_call(
            DOMAIN,
            "refresh_power_zones",
            {"config_entry_id": entry.entry_id},
            blocking=True,
        )
        # Fire-and-forget — the actual refresh runs in a background task.
        await hass.async_block_till_done(wait_background_tasks=True)

    power_zones_spy.assert_awaited_once_with()
    workout_spy.assert_not_awaited()


async def test_refresh_power_zones_works_without_config_entry_id(
    hass: HomeAssistant,
) -> None:
    """Single-account installs can omit ``config_entry_id``."""
    entry = await _setup_entry(hass)
    power_zones_coordinator = entry.runtime_data.power_zones_coordinator

    with patch.object(power_zones_coordinator, "async_refresh", new=AsyncMock()) as power_zones_spy:
        await hass.services.async_call(
            DOMAIN,
            "refresh_power_zones",
            {},
            blocking=True,
        )
        await hass.async_block_till_done(wait_background_tasks=True)

    power_zones_spy.assert_awaited_once_with()
