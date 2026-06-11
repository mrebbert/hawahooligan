"""Regression: picker + lifetime sensors stay available when the API fails.

A user reported the workout picker going "unavailable" in the dashboard
every time their Wahoo Sandbox quota was exhausted — even though the
picker reads from the local ``workouts.json`` mirror and doesn't need
an API call. Same applied to the lifetime totals, which come from the
persistent ``Store`` loaded at setup.

The root cause was the default ``CoordinatorEntity.available`` tying
itself to ``coordinator.last_update_success``. When the coordinator's
``_async_update_data`` raised ``UpdateFailed`` (rate limit on the
listing endpoint), every entity attached to that coordinator went
unavailable — including the ones backed by local state.

These tests pin the fix: ``available=True`` for the picker and for
every ``WahooLifetimeSensor`` regardless of coordinator poll state.
The per-workout sensors (``_distance``, ``_power_avg``,
``_last_workout``, …) are NOT touched — they correctly reflect the
freshness of the API data they expose.
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
        unique_id="local-state-availability-probe",
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


def _simulate_coordinator_failure(coordinator) -> None:
    """Flip the coordinator into the same state a 429 on listing produces."""
    coordinator.last_update_success = False


async def test_picker_stays_available_after_coordinator_failure(
    hass: HomeAssistant,
) -> None:
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    picker = next(
        ent
        for ent in hass.data["entity_components"]["select"].entities
        if ent.platform.platform_name == DOMAIN
    )

    # Baseline: available with a healthy coordinator.
    assert picker.available is True

    # Simulate the rate-limit failure shape.
    _simulate_coordinator_failure(coordinator)
    assert picker.available is True, (
        "picker reads from the local manifest mirror — coordinator API "
        "failure should not flip it unavailable"
    )


async def test_lifetime_sensors_stay_available_after_coordinator_failure(
    hass: HomeAssistant,
) -> None:
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    lifetime_sensors = [
        ent
        for ent in hass.data["entity_components"]["sensor"].entities
        if ent.platform.platform_name == DOMAIN
        and ent.entity_id.startswith("sensor.hawahooligan_lifetime_")
    ]
    assert len(lifetime_sensors) == 7, (
        f"expected 7 lifetime sensors, got {len(lifetime_sensors)} — has the "
        f"LIFETIME_SENSORS tuple changed?"
    )

    for sensor in lifetime_sensors:
        assert sensor.available is True, f"{sensor.entity_id} unavailable pre-failure"

    _simulate_coordinator_failure(coordinator)

    for sensor in lifetime_sensors:
        assert sensor.available is True, (
            f"{sensor.entity_id} went unavailable on coordinator API failure "
            "even though lifetime totals come from the persistent Store"
        )


async def test_per_workout_sensors_follow_coordinator_data_not_update_success(
    hass: HomeAssistant,
) -> None:
    """Per-workout sensors stay available with cached data; go unavailable when empty.

    Contract since 0.7.17 (persistent detail cache): the per-workout
    sensors track ``coordinator.data is not None`` instead of
    ``last_update_success``. With cached data they stay available
    through a rate-limit storm — that's the whole point of the cache.
    Without any data at all (cold start, no cache, no successful poll)
    they're unavailable, which is the only honest signal.
    """
    from custom_components.hawahooligan.coordinator import WorkoutData

    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    api_bound_sensors = [
        ent
        for ent in hass.data["entity_components"]["sensor"].entities
        if ent.platform.platform_name == DOMAIN
        and ent.entity_id.startswith("sensor.hawahooligan_")
        and not ent.entity_id.startswith("sensor.hawahooligan_lifetime_")
        and ent.entity_id
        not in {
            # FTP / Critical Power live on the power_zones coordinator;
            # they're untouched by the workout coordinator's poll state.
            "sensor.hawahooligan_ftp",
            "sensor.hawahooligan_critical_power",
        }
    ]
    assert api_bound_sensors, "no API-bound per-workout sensors found — wiring broke?"

    # Seed cached data + simulate a failed poll: sensors stay available.
    coordinator.async_set_updated_data(WorkoutData(workout_id=42, name="cached ride"))
    _simulate_coordinator_failure(coordinator)
    for sensor in api_bound_sensors:
        assert sensor.available is True, (
            f"{sensor.entity_id} went unavailable despite cached data — "
            "0.7.17's persistent detail cache is supposed to keep these "
            "sensors usable through rate-limit storms"
        )

    # Cold start (no data, no successful poll): sensors are unavailable.
    coordinator.data = None
    for sensor in api_bound_sensors:
        assert sensor.available is False, (
            f"{sensor.entity_id} reported available without any data — "
            "would render as 'unknown' with no honest signal to the user"
        )
