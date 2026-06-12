"""Regression: per-workout sensors come up populated from the cache after restart.

A user reported that ``Time & distance`` and ``Power & body`` entities
showed "unavailable" after restart on a rate-limited Sandbox account —
the lifetime totals and picker survived because they're already
backed by persistent storage, but the per-workout detail cache lived
in memory only and was lost on every restart.

0.7.17 persists the detail cache to ``hawahooligan_details_<entry_id>``
and seeds ``coordinator.data`` from it during setup. This test pins
the contract: a pre-seeded cache restored at setup must populate the
per-workout sensors with their cached values even when the API can't
reach Wahoo on the first refresh.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches

# Known entry_id pins the Store key so the pre-seeded payload lands
# where ``async_load_details_cache`` will look.
_ENTRY_ID = "details-cache-probe"
_DETAILS_STORE_KEY = f"{DOMAIN}_details_{_ENTRY_ID}"


async def test_setup_seeds_coordinator_data_from_cache(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Coordinator loads the cache and seeds ``self.data`` for the pinned id."""
    # Pre-seed the details store with one known workout.
    hass_storage[_DETAILS_STORE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": _DETAILS_STORE_KEY,
        "data": {
            "version": 1,
            "workouts": {
                "9001": {
                    "workout_id": 9001,
                    "name": "Cached evening ride",
                    "starts": "2026-06-10T18:00:00Z",
                    "indoor": False,
                    "manual": False,
                    "distance_km": 42.0,
                    "power_avg_w": 220.0,
                    "heart_rate_avg_bpm": 152.0,
                }
            },
        },
    }
    # Pre-seed the workouts manifest with selected_id=9001 so the
    # coordinator knows which cached workout to seed.
    from pathlib import Path

    from custom_components.hawahooligan.const import WWW_SUBPATH
    from custom_components.hawahooligan.manifest import MANIFEST_FILENAME

    geojson_dir = Path(hass.config.path(*WWW_SUBPATH))
    geojson_dir.mkdir(parents=True, exist_ok=True)
    (geojson_dir / MANIFEST_FILENAME).write_text(
        '{"workouts": [{"id": 9001, "name": "Cached evening ride"}], "selected_id": 9001}',
        encoding="utf-8",
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="details-cache-seed-probe",
        entry_id=_ENTRY_ID,
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

    coordinator = entry.runtime_data.coordinator
    # The pinned id was restored from the manifest.
    assert coordinator.selected_workout_id == 9001
    # The cache loaded the seeded workout into the in-memory dict.
    assert 9001 in coordinator._detail_cache
    cached = coordinator._detail_cache[9001]
    assert cached.name == "Cached evening ride"
    assert cached.distance_km == 42.0
    assert cached.power_avg_w == 220.0
    assert cached.heart_rate_avg_bpm == 152.0


async def test_sensors_available_from_cache_when_api_refresh_failed(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Cold start + rate-limited API: per-workout sensors still come up populated.

    Pre-seed the cache, force the first refresh to raise UpdateFailed,
    assert the per-workout sensors are still available (from cache) and
    report the cached values.
    """
    hass_storage[_DETAILS_STORE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": _DETAILS_STORE_KEY,
        "data": {
            "version": 1,
            "workouts": {
                "9002": {
                    "workout_id": 9002,
                    "name": "Cached morning ride",
                    "starts": "2026-06-10T07:00:00Z",
                    "indoor": False,
                    "manual": False,
                    "distance_km": 18.5,
                    "power_avg_w": 180.0,
                }
            },
        },
    }
    # Manifest pinning the cached id.
    from pathlib import Path

    from custom_components.hawahooligan.const import WWW_SUBPATH
    from custom_components.hawahooligan.manifest import MANIFEST_FILENAME

    geojson_dir = Path(hass.config.path(*WWW_SUBPATH))
    geojson_dir.mkdir(parents=True, exist_ok=True)
    (geojson_dir / MANIFEST_FILENAME).write_text(
        '{"workouts": [{"id": 9002, "name": "Cached morning ride"}], "selected_id": 9002}',
        encoding="utf-8",
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="details-cache-rate-limited-probe",
        entry_id=_ENTRY_ID,
    )
    entry.add_to_hass(hass)

    from homeassistant.helpers.update_coordinator import UpdateFailed

    async def _api_429(*_args, **_kwargs):
        raise UpdateFailed("simulated 429")

    with (
        oauth_implementation_patches(),
        patch("custom_components.hawahooligan.WahooApi", return_value=MagicMock()),
        patch(
            "custom_components.hawahooligan.WahooCoordinator._async_update_data",
            new=_api_429,
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
    # Coordinator's last poll failed but data survives from cache seed.
    assert coordinator.last_update_success is False
    assert coordinator.data is not None
    assert coordinator.data.name == "Cached morning ride"
    assert coordinator.data.distance_km == 18.5

    # Per-workout sensors report available from the cached data.
    distance_sensor = next(
        ent
        for ent in hass.data["entity_components"]["sensor"].entities
        if ent.entity_id == "sensor.hawahooligan_distance"
    )
    assert distance_sensor.available is True
    assert distance_sensor.native_value == 18.5

    last_workout_sensor = next(
        ent
        for ent in hass.data["entity_components"]["sensor"].entities
        if ent.entity_id == "sensor.hawahooligan_last_workout"
    )
    assert last_workout_sensor.available is True


async def test_workout_data_storage_round_trip() -> None:
    """Serializer + deserializer preserve the workout fields, drop transient ones."""
    from custom_components.hawahooligan.coordinator import (
        WorkoutData,
        workout_data_from_storage,
        workout_data_to_storage,
    )
    from custom_components.hawahooligan.manifest import RecentWorkout

    original = WorkoutData(
        workout_id=1234,
        name="Round trip",
        starts="2026-06-10T07:00:00Z",
        indoor=False,
        manual=False,
        distance_km=50.5,
        power_avg_w=210.0,
        recent=[
            RecentWorkout(
                id=999,
                name="picker context",
                starts=None,
                workout_type_id=0,
                workout_type_name="Biking",
                indoor=False,
                manual=False,
                has_track=True,
            )
        ],
        selected_workout_id=1234,
    )
    serialized = workout_data_to_storage(original)
    # Transient picker context drops out — the cache is workout-scoped.
    assert "recent" not in serialized
    assert "selected_workout_id" not in serialized

    rehydrated = workout_data_from_storage(serialized)
    assert rehydrated is not None
    assert rehydrated.workout_id == 1234
    assert rehydrated.name == "Round trip"
    assert rehydrated.distance_km == 50.5
    assert rehydrated.power_avg_w == 210.0
    # Transient fields default to empty.
    assert rehydrated.recent == []
    assert rehydrated.selected_workout_id is None


async def test_workout_data_from_storage_tolerates_unknown_fields() -> None:
    """Forward-compat: an old cache file with extra fields still loads."""
    from custom_components.hawahooligan.coordinator import workout_data_from_storage

    payload = {
        "workout_id": 5555,
        "name": "Future schema",
        "distance_km": 30.0,
        # Hypothetical future field we don't know about yet.
        "elevation_gain_m": 500.0,
        "weather_summary": "sunny",
    }
    result = workout_data_from_storage(payload)
    assert result is not None
    assert result.workout_id == 5555
    assert result.distance_km == 30.0
