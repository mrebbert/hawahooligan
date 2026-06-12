"""Regression: a select_workout right before HA shuts down is not lost.

The detail cache is written through ``Store.async_delay_save`` with a
10-second debounce so backfill loops don't hit disk per workout.
That coalescing is correct under load but risky on shutdown: if HA
stops inside the debounce window, the pending payload must still
flush — otherwise users would silently lose their last selection
across restarts.

HA's ``Store`` provides this guarantee via a one-shot listener on
``EVENT_HOMEASSISTANT_FINAL_WRITE``. These tests pin both halves:

- ``_schedule_details_save`` registers the listener (i.e. our wiring
  is correct).
- Firing the final-write event actually flushes the latest payload.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches

_ENTRY_ID = "details-cache-debounce-probe"
_DETAILS_STORE_KEY = f"{DOMAIN}_details_{_ENTRY_ID}"


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="debounce-probe",
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
    return entry


async def test_schedule_details_save_registers_final_write_listener(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """First ``_schedule_details_save`` call wires the shutdown flush.

    Without this listener, a debounced write that hasn't fired yet
    when HA stops is silently dropped.
    """
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator

    # Seed the cache with a fresh workout selection.
    coordinator._detail_cache[1234] = WorkoutData(
        workout_id=1234, name="Pending ride", distance_km=25.0
    )

    # Before scheduling, no listener exists.
    assert coordinator._details_store._unsub_final_write_listener is None

    coordinator._schedule_details_save()

    # The listener now exists — the final-write event will flush the
    # pending payload before HA finishes shutting down.
    assert coordinator._details_store._unsub_final_write_listener is not None


async def test_final_write_event_flushes_pending_payload(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """A select_workout 1 second before shutdown still lands on disk.

    Simulates the realistic race: user picks a workout → HA stops
    before the 10s debounce expires → the cache must still contain
    the new selection after the next restart.
    """
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator

    coordinator._detail_cache[5050] = WorkoutData(
        workout_id=5050,
        name="Last-second pick",
        distance_km=18.5,
        power_avg_w=190.0,
    )
    coordinator._schedule_details_save()

    # Cache file does NOT yet reflect the new entry — debounce hasn't expired.
    pre_shutdown = hass_storage.get(_DETAILS_STORE_KEY) or {}
    pre_workouts = (pre_shutdown.get("data") or {}).get("workouts") or {}
    assert "5050" not in pre_workouts

    # HA's shutdown sequence emits FINAL_WRITE; Store listens once and flushes.
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()

    # Post-shutdown: the cache file contains the pending selection.
    post_shutdown = hass_storage[_DETAILS_STORE_KEY]
    workouts = post_shutdown["data"]["workouts"]
    assert "5050" in workouts
    assert workouts["5050"]["name"] == "Last-second pick"
    assert workouts["5050"]["distance_km"] == 18.5
    assert workouts["5050"]["power_avg_w"] == 190.0
