"""Regression: rolling-window sensors register and read from the cache.

Tier-2 smoke test for the 0.7.20 trailing-window sensors. The arithmetic
is covered exhaustively in ``tests/test_rolling.py``; this test just
pins the HA wiring — that the sensors:

- Get registered with the expected entity_ids.
- Stay available even when the coordinator's last poll failed (their
  data source is the local cache, same contract as the lifetime totals).
- Pick up cached workout details and project the right metric.
- Surface the indoor / outdoor split on the metrics that have one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches


async def _setup_with_cache(
    hass: HomeAssistant,
    *,
    detail_cache: dict[int, WorkoutData],
    workouts_index: dict[int, dict],
) -> MockConfigEntry:
    """Boot the entry with a pre-seeded cache + index."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="rolling-sensor-probe",
        entry_id="rolling-sensor-probe",
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
    # Seed the cache + index AFTER setup so the seeded state survives.
    coordinator = entry.runtime_data.coordinator
    coordinator._detail_cache.update(detail_cache)
    coordinator._workouts_index.update(workouts_index)
    return entry


def _get_sensor(hass: HomeAssistant, entity_id: str):
    return next(
        ent
        for ent in hass.data["entity_components"]["sensor"].entities
        if ent.entity_id == entity_id
    )


async def test_all_eight_rolling_sensors_register_with_stable_ids(
    hass: HomeAssistant,
) -> None:
    """Pin the entity_id slugs — Lovelace YAML in dashboard/dashboard.yaml depends on them."""
    await _setup_with_cache(hass, detail_cache={}, workouts_index={})

    registered = {
        ent.entity_id
        for ent in hass.data["entity_components"]["sensor"].entities
        if ent.entity_id.startswith("sensor.hawahooligan_rolling_")
    }
    expected = {
        "sensor.hawahooligan_rolling_distance_7d",
        "sensor.hawahooligan_rolling_distance_28d",
        "sensor.hawahooligan_rolling_duration_7d",
        "sensor.hawahooligan_rolling_duration_28d",
        "sensor.hawahooligan_rolling_workouts_7d",
        "sensor.hawahooligan_rolling_workouts_28d",
        "sensor.hawahooligan_rolling_tss_7d",
        "sensor.hawahooligan_rolling_tss_28d",
    }
    assert registered == expected, (
        f"rolling sensor wiring drifted — registered={registered}, expected={expected}"
    )


async def test_rolling_sensors_sum_recent_workouts_from_cache(
    hass: HomeAssistant,
) -> None:
    """7d sensor sums the workouts whose ``starts`` falls in the trailing 7 days."""
    now = datetime.now(UTC)
    # Three workouts in window, one well outside.
    workouts_index = {
        100: {"starts": (now - timedelta(days=1)).isoformat()},
        200: {"starts": (now - timedelta(days=3)).isoformat()},
        300: {"starts": (now - timedelta(days=5)).isoformat()},
        400: {"starts": (now - timedelta(days=20)).isoformat()},
    }
    detail_cache = {
        100: WorkoutData(
            workout_id=100, indoor=False, distance_km=30.0, duration_min=90.0, tss=70.0
        ),
        200: WorkoutData(
            workout_id=200, indoor=True, distance_km=18.0, duration_min=45.0, tss=55.0
        ),
        300: WorkoutData(
            workout_id=300, indoor=False, distance_km=42.0, duration_min=120.0, tss=80.0
        ),
        400: WorkoutData(
            workout_id=400, indoor=False, distance_km=200.0, duration_min=600.0, tss=350.0
        ),
    }
    await _setup_with_cache(hass, detail_cache=detail_cache, workouts_index=workouts_index)

    distance_7d = _get_sensor(hass, "sensor.hawahooligan_rolling_distance_7d")
    # 30 + 18 + 42 = 90 (the 200km outdoor ride is outside 7d)
    assert distance_7d.native_value == 90.0
    assert distance_7d.available is True

    duration_7d = _get_sensor(hass, "sensor.hawahooligan_rolling_duration_7d")
    assert duration_7d.native_value == 255.0  # 90 + 45 + 120

    workouts_7d = _get_sensor(hass, "sensor.hawahooligan_rolling_workouts_7d")
    assert workouts_7d.native_value == 3

    tss_7d = _get_sensor(hass, "sensor.hawahooligan_rolling_tss_7d")
    assert tss_7d.native_value == 205.0  # 70 + 55 + 80

    # 28d sensor catches the outlier too.
    distance_28d = _get_sensor(hass, "sensor.hawahooligan_rolling_distance_28d")
    assert distance_28d.native_value == 290.0  # 30 + 18 + 42 + 200


async def test_rolling_sensors_expose_indoor_outdoor_split_as_attributes(
    hass: HomeAssistant,
) -> None:
    """Distance / duration / workout-count sensors carry split sub-sums.

    Same shape contract as the lifetime sensors so Lovelace templates
    can treat both families uniformly.
    """
    now = datetime.now(UTC)
    workouts_index = {
        1: {"starts": (now - timedelta(days=1)).isoformat()},
        2: {"starts": (now - timedelta(days=2)).isoformat()},
    }
    detail_cache = {
        1: WorkoutData(workout_id=1, indoor=False, distance_km=30.0, duration_min=90.0),
        2: WorkoutData(workout_id=2, indoor=True, distance_km=12.0, duration_min=45.0),
    }
    await _setup_with_cache(hass, detail_cache=detail_cache, workouts_index=workouts_index)

    distance_7d = _get_sensor(hass, "sensor.hawahooligan_rolling_distance_7d")
    attrs = distance_7d.extra_state_attributes
    assert attrs is not None
    assert attrs["outdoor"] == 30.0
    assert attrs["indoor"] == 12.0

    workouts_7d = _get_sensor(hass, "sensor.hawahooligan_rolling_workouts_7d")
    wattrs = workouts_7d.extra_state_attributes
    assert wattrs is not None
    assert wattrs["outdoor"] == 1
    assert wattrs["indoor"] == 1

    # TSS sensor has no split — attribute dict is None.
    tss_7d = _get_sensor(hass, "sensor.hawahooligan_rolling_tss_7d")
    assert tss_7d.extra_state_attributes is None


async def test_rolling_sensors_stay_available_with_empty_cache(
    hass: HomeAssistant,
) -> None:
    """Zero is the honest answer for a cold-start install — not 'unavailable'.

    The dashboard cards should render "0 km this week" the moment the
    user installs the integration, not blank tiles that read 'unknown'.
    """
    await _setup_with_cache(hass, detail_cache={}, workouts_index={})

    distance_7d = _get_sensor(hass, "sensor.hawahooligan_rolling_distance_7d")
    assert distance_7d.available is True
    assert distance_7d.native_value == 0.0
