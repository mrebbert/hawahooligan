"""Regression: ``async_select_workout`` auto-renders missing outdoor tracks.

The initial backfill only renders the 20 newest workouts and
``full_backfill`` defaults to ``with_tracks=False`` — so users routinely
have outdoor rides in their lifetime totals (and in the picker)
without a matching ``.geojson`` on disk. Picking one of those rides
used to land on the iframe's "no GPS track" overlay even though Wahoo
held the data; from 0.7.13 the coordinator kicks off a background
render the moment the pick lands.

These tests pin the decision logic — auto-render fires for genuine
outdoor + non-manual + no-track picks and stays off for indoor / manual
/ already-rendered / "Latest" cases so we don't waste a detail call.
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
        unique_id="auto-render-probe",
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


def _seed(coordinator) -> None:
    """Three workouts: outdoor-no-track, outdoor-has-track, indoor, manual."""
    coordinator._workouts_index = {
        2001: {
            "id": 2001,
            "name": "Old outdoor without track",
            "starts": "2026-05-01T08:00:00Z",
            "indoor": False,
            "manual": False,
            "has_track": False,
        },
        2002: {
            "id": 2002,
            "name": "Recent outdoor with track",
            "starts": "2026-06-01T08:00:00Z",
            "indoor": False,
            "manual": False,
            "has_track": True,
        },
        2003: {
            "id": 2003,
            "name": "Indoor trainer",
            "starts": "2026-06-05T18:00:00Z",
            "indoor": True,
            "manual": False,
            "has_track": False,
        },
        2004: {
            "id": 2004,
            "name": "Manual entry",
            "starts": "2026-06-06T19:00:00Z",
            "indoor": False,
            "manual": True,
            "has_track": False,
        },
    }


async def test_outdoor_without_track_triggers_auto_render(
    hass: HomeAssistant,
) -> None:
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    _seed(coordinator)

    with patch.object(
        coordinator, "async_render_workout", new=AsyncMock(return_value=None)
    ) as render_spy:
        await coordinator.async_select_workout(2001)
        await hass.async_block_till_done()

    render_spy.assert_awaited_once_with(2001)


async def test_outdoor_with_track_skips_render(hass: HomeAssistant) -> None:
    """Already-rendered tracks shouldn't burn a detail call."""
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    _seed(coordinator)

    with patch.object(coordinator, "async_render_workout", new=AsyncMock()) as render_spy:
        await coordinator.async_select_workout(2002)
        await hass.async_block_till_done()

    render_spy.assert_not_awaited()


async def test_indoor_pick_skips_render(hass: HomeAssistant) -> None:
    """Indoor rides have no GPS by definition."""
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    _seed(coordinator)

    with patch.object(coordinator, "async_render_workout", new=AsyncMock()) as render_spy:
        await coordinator.async_select_workout(2003)
        await hass.async_block_till_done()

    render_spy.assert_not_awaited()


async def test_manual_pick_skips_render(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    _seed(coordinator)

    with patch.object(coordinator, "async_render_workout", new=AsyncMock()) as render_spy:
        await coordinator.async_select_workout(2004)
        await hass.async_block_till_done()

    render_spy.assert_not_awaited()


async def test_latest_sentinel_skips_render(hass: HomeAssistant) -> None:
    """``None`` means "follow latest" — that's the regular poll's job."""
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    _seed(coordinator)
    # Pin to 2001 first so async_select_workout sees a real transition to None.
    await coordinator.async_select_workout(2001)
    await hass.async_block_till_done()

    with patch.object(coordinator, "async_render_workout", new=AsyncMock()) as render_spy:
        await coordinator.async_select_workout(None)
        await hass.async_block_till_done()

    render_spy.assert_not_awaited()


async def test_unknown_id_skips_render(hass: HomeAssistant) -> None:
    """Don't auto-render workouts the index doesn't know about.

    The index lookup is how we tell indoor / manual from outdoor without
    spending a detail call. An unknown id forces a fallback: let the
    user trigger ``hawahooligan.render_workout`` explicitly.
    """
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    _seed(coordinator)

    with patch.object(coordinator, "async_render_workout", new=AsyncMock()) as render_spy:
        await coordinator.async_select_workout(99999)
        await hass.async_block_till_done()

    render_spy.assert_not_awaited()
