"""Regression: streak sensor registers and reads the local-TZ streak."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches


async def _setup_with_index(
    hass: HomeAssistant, workouts_index: dict[int, dict]
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="streak-sensor-probe",
        entry_id="streak-sensor-probe",
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
    entry.runtime_data.coordinator._workouts_index.update(workouts_index)
    return entry


def _get_sensor(hass: HomeAssistant, entity_id: str):
    return next(
        ent
        for ent in hass.data["entity_components"]["sensor"].entities
        if ent.entity_id == entity_id
    )


async def test_streak_sensor_registers_with_stable_entity_id(
    hass: HomeAssistant,
) -> None:
    """Pin the entity_id — Lovelace YAML depends on it."""
    await _setup_with_index(hass, {})

    sensor = _get_sensor(hass, "sensor.hawahooligan_streak")
    assert sensor is not None
    assert sensor.available is True
    # Empty index → 0 streak. Honest "no workouts yet" state, not unavailable.
    assert sensor.native_value == 0


async def test_streak_sensor_counts_consecutive_days_from_today(
    hass: HomeAssistant,
) -> None:
    """Three workouts on consecutive days ending today → streak = 3."""
    now = datetime.now(UTC)
    workouts_index = {
        1: {"starts": (now - timedelta(days=2)).isoformat()},
        2: {"starts": (now - timedelta(days=1)).isoformat()},
        3: {"starts": now.isoformat()},
    }
    await _setup_with_index(hass, workouts_index)

    sensor = _get_sensor(hass, "sensor.hawahooligan_streak")
    assert sensor.native_value == 3


async def test_streak_sensor_exposes_longest_and_dates_as_attributes(
    hass: HomeAssistant,
) -> None:
    """Longest streak + start/last dates ride along for "x days, started Mon" cards."""
    now = datetime.now(UTC)
    workouts_index = {
        1: {"starts": (now - timedelta(days=1)).isoformat()},
        2: {"starts": now.isoformat()},
    }
    await _setup_with_index(hass, workouts_index)

    sensor = _get_sensor(hass, "sensor.hawahooligan_streak")
    attrs = sensor.extra_state_attributes
    assert attrs is not None
    assert attrs["longest_streak"] == 2
    assert "current_streak_start_date" in attrs
    assert "last_workout_date" in attrs
    # Dates are ISO strings — directly usable in template sensors / cards
    # without a strftime detour.
    assert isinstance(attrs["last_workout_date"], str)
    assert len(attrs["last_workout_date"]) == 10  # YYYY-MM-DD


async def test_streak_broken_returns_zero_with_longest_preserved(
    hass: HomeAssistant,
) -> None:
    """Last workout 5 days ago → current=0, longest reflects historic best."""
    now = datetime.now(UTC)
    workouts_index = {
        1: {"starts": (now - timedelta(days=7)).isoformat()},
        2: {"starts": (now - timedelta(days=6)).isoformat()},
        3: {"starts": (now - timedelta(days=5)).isoformat()},
        # Gap of 5+ days — current streak is broken.
    }
    await _setup_with_index(hass, workouts_index)

    sensor = _get_sensor(hass, "sensor.hawahooligan_streak")
    assert sensor.native_value == 0
    attrs = sensor.extra_state_attributes
    assert attrs is not None
    assert attrs["longest_streak"] == 3
    # current_streak_start_date is omitted when there's no current streak.
    assert "current_streak_start_date" not in attrs
    # last_workout_date is still present — useful for "last trained N days ago".
    assert "last_workout_date" in attrs
