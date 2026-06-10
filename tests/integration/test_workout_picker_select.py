"""Regression: ``select.hawahooligan_workout_picker`` mirrors + drives the coordinator.

Pins three contracts:

1. ``options`` lists the ``Latest`` sentinel plus one entry per workout in
   ``coordinator._workouts_index`` (sorted newest first).
2. ``current_option`` follows ``coordinator.selected_workout_id``.
3. Calling ``async_select_option`` dispatches to
   ``coordinator.async_select_workout`` with the corresponding workout id
   (or ``None`` for the ``Latest`` sentinel).

Backstop against silent regressions if the manifest accumulator,
listener push, or label parser drift apart.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches

_LATEST_OPTION = "⏵ Latest workout"


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="workout-picker-probe",
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


def _seed_index(coordinator) -> None:
    """Push three synthetic workouts into the coordinator's in-memory index.

    Mix of indoor + manual + outdoor so the icon + ``has_track`` logic
    gets exercised. ``starts`` values are spread across three days so the
    ``newest-first`` sort is observable.
    """
    coordinator._workouts_index = {
        1001: {
            "id": 1001,
            "name": "Wednesday loop",
            "starts": "2026-06-10T07:00:00Z",
            "workout_type_id": 0,
            "workout_type": "Biking",
            "indoor": False,
            "manual": False,
            "has_track": True,
            "duration_min": 75.0,  # 1:15 h
        },
        1002: {
            "id": 1002,
            "name": "Indoor trainer",
            "starts": "2026-06-09T17:30:00Z",
            "workout_type_id": 0,
            "workout_type": "Biking",
            "indoor": True,
            "manual": False,
            "has_track": False,
            "duration_min": 45.0,  # 45 min
        },
        1003: {
            "id": 1003,
            "name": "Manual import",
            "starts": "2026-06-08T18:00:00Z",
            "workout_type_id": 0,
            "workout_type": "Biking",
            "indoor": False,
            "manual": True,
            "has_track": False,
            # No duration → label omits it gracefully.
        },
    }


async def test_options_list_latest_sentinel_then_workouts_newest_first(
    hass: HomeAssistant,
) -> None:
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    _seed_index(coordinator)

    select_entities = [
        ent
        for ent in hass.data["entity_components"]["select"].entities
        if ent.platform.platform_name == DOMAIN
    ]
    assert len(select_entities) == 1, "exactly one workout-picker per entry"
    picker = select_entities[0]

    options = picker.options
    assert options[0] == _LATEST_OPTION, "Latest sentinel must always lead the list"
    # Workouts sorted newest first: 1001 (2026-06-10) → 1002 (06-09) → 1003 (06-08).
    assert " Wednesday loop " in f" {options[1]} ", "newest outdoor ride at index 1"
    assert " Indoor trainer " in f" {options[2]} ", "indoor ride at index 2"
    assert " Manual import " in f" {options[3]} ", "manual ride at index 3"
    # Icons distinguish indoor / manual / outdoor visually.
    assert "🚴" in options[1]
    assert "🏠" in options[2]
    assert "📝" in options[3]
    # ISO date prefix keeps lexical + chronological sort aligned.
    assert options[1].startswith("2026-06-10")
    assert options[2].startswith("2026-06-09")
    assert options[3].startswith("2026-06-08")
    # Duration is rendered when present, omitted (gracefully) when absent.
    assert "1:15 h" in options[1], "75-minute ride should show as 1:15 h"
    assert "45 min" in options[2], "under-an-hour ride should show as MM min"
    assert " min" not in options[3] and " h" not in options[3], (
        "label must omit duration cleanly when the source didn't supply one"
    )


async def test_current_option_follows_selected_workout_id(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    _seed_index(coordinator)

    picker = next(
        ent
        for ent in hass.data["entity_components"]["select"].entities
        if ent.platform.platform_name == DOMAIN
    )

    # No selection → Latest sentinel reflects in the state.
    assert coordinator.selected_workout_id is None
    assert picker.current_option == _LATEST_OPTION

    # Pin a known id → current_option matches that workout's label.
    coordinator._selected_workout_id = 1002
    assert "Indoor trainer" in picker.current_option

    # Pin an id we've never seen → fallback shape so the user still sees the pin.
    coordinator._selected_workout_id = 9999
    assert picker.current_option == "#9999"


async def test_async_select_option_dispatches_to_coordinator(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    _seed_index(coordinator)

    picker = next(
        ent
        for ent in hass.data["entity_components"]["select"].entities
        if ent.platform.platform_name == DOMAIN
    )
    # Rebuild option map.
    options = picker.options
    indoor_label = next(label for label in options if "Indoor trainer" in label)

    with patch.object(coordinator, "async_select_workout", new=AsyncMock()) as dispatch:
        await picker.async_select_option(indoor_label)
    dispatch.assert_awaited_once_with(1002)

    with patch.object(coordinator, "async_select_workout", new=AsyncMock()) as dispatch:
        await picker.async_select_option(_LATEST_OPTION)
    dispatch.assert_awaited_once_with(None)
