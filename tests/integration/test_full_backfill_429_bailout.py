"""Regression: ``async_full_backfill`` bails after 3 consecutive 429s.

The smaller sibling ``async_backfill_recent`` got this guard in 0.7.5;
``async_full_backfill`` shipped without it and was happy to walk an
entire 200-page listing burning every detail call against an exhausted
quota. 0.7.14 ports the same 3-strike bail-out so a rate-limited account
stops floodlighting Wahoo's hourly / daily caps.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.api import WahooApiError
from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches


async def test_full_backfill_bails_after_three_consecutive_429s(
    hass: HomeAssistant,
) -> None:
    """Detail-loop 429s → break out after exactly 3 attempts.

    Setup wires a single page with 8 workouts so the loop has plenty of
    room to keep retrying if it ignored the strike count.
    """
    mock_api = MagicMock()
    mock_api.async_get_workouts = AsyncMock(
        return_value={"workouts": [{"id": i} for i in range(7001, 7009)]}
    )
    # Every detail call goes 429 — the rolling-window budget can't see
    # Wahoo's hourly cap, so without the strike guard the loop would
    # eat the whole listing.
    mock_api.async_get_workout = AsyncMock(
        side_effect=WahooApiError("rate limited", status_code=429)
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="full-backfill-429-probe",
    )
    entry.add_to_hass(hass)

    with (
        oauth_implementation_patches(),
        patch("custom_components.hawahooligan.WahooApi", return_value=mock_api),
        patch(
            "custom_components.hawahooligan.WahooCoordinator._async_update_data",
            new=AsyncMock(return_value=WorkoutData(workout_id=None)),
        ),
        patch(
            "custom_components.hawahooligan.WahooPowerZonesCoordinator.async_config_entry_first_refresh",
            new=AsyncMock(),
        ),
        # The first-setup recent backfill is unrelated to this test.
        patch(
            "custom_components.hawahooligan.WahooCoordinator.async_backfill_recent",
            new=AsyncMock(return_value=0),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data.coordinator

        await coordinator.async_full_backfill(
            with_tracks=False,
            max_pages=10,
            max_calls_per_window=100,
            window_seconds=300,
        )

    # 1 listing call (page 1) + exactly 3 detail calls (3 strikes, break).
    assert mock_api.async_get_workouts.call_count == 1
    assert mock_api.async_get_workout.call_count == 3, (
        f"expected exactly 3 detail calls before bail-out, got "
        f"{mock_api.async_get_workout.call_count}"
    )


async def test_full_backfill_listing_429_aborts_immediately(hass: HomeAssistant) -> None:
    """A 429 on the listing call itself aborts without touching detail."""
    mock_api = MagicMock()
    mock_api.async_get_workouts = AsyncMock(
        side_effect=WahooApiError("rate limited on listing", status_code=429)
    )
    mock_api.async_get_workout = AsyncMock()

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="full-backfill-listing-429-probe",
    )
    entry.add_to_hass(hass)

    with (
        oauth_implementation_patches(),
        patch("custom_components.hawahooligan.WahooApi", return_value=mock_api),
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
        coordinator = entry.runtime_data.coordinator

        added = await coordinator.async_full_backfill(
            with_tracks=False,
            max_pages=10,
            max_calls_per_window=100,
            window_seconds=300,
        )

    assert added == 0
    # The detail endpoint must never have been touched.
    assert mock_api.async_get_workout.call_count == 0
