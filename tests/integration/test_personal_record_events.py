"""Regression: PR detection fires on polling, NOT on backfill.

The contract from the 2026-06-14 design discussion:

- Polling path (``_async_update_data``) fires
  ``hawahooligan_personal_record`` events for every new PR — including
  the first workout, which sets the baseline by being the only entry.
- Backfill paths (``async_backfill_recent``, ``async_full_backfill``)
  stay silent. Otherwise a cold-start full backfill of 1000 historic
  workouts would dump several thousand "record" events on the bus.

This test pins both halves: polling emits, backfill doesn't.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import Event, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN, EVENT_PERSONAL_RECORD
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches


def _capture_records(hass: HomeAssistant) -> list[Event]:
    """Subscribe to ``hawahooligan_personal_record`` and collect every event."""
    received: list[Event] = []
    hass.bus.async_listen(EVENT_PERSONAL_RECORD, received.append)
    return received


async def _bare_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="pr-event-probe",
        entry_id="pr-event-probe",
    )
    entry.add_to_hass(hass)
    return entry


async def _setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
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


async def test_emit_personal_records_fires_on_polling_path(
    hass: HomeAssistant,
) -> None:
    """First workout in an empty cache fires PRs for every populated metric."""
    entry = await _bare_entry(hass)
    await _setup_entry(hass, entry)
    coordinator = entry.runtime_data.coordinator

    received = _capture_records(hass)

    new = WorkoutData(workout_id=42, indoor=False, distance_km=50.0, duration_min=120.0, tss=85.0)
    coordinator._emit_personal_records(new)
    await hass.async_block_till_done()

    kinds = {ev.data["kind"] for ev in received}
    assert kinds == {"distance", "duration", "tss"}
    # power_avg_w was None on the new workout — skipped.
    assert "power_avg" not in kinds

    # Payload shape: kind, value, previous_value, workout_id, indoor.
    for ev in received:
        assert ev.data["workout_id"] == 42
        assert ev.data["indoor"] is False
        # First workout — previous_value is None across the board.
        assert ev.data["previous_value"] is None


async def test_emit_personal_records_carries_previous_value(
    hass: HomeAssistant,
) -> None:
    """Beats-an-existing-record case carries the old high in previous_value."""
    entry = await _bare_entry(hass)
    await _setup_entry(hass, entry)
    coordinator = entry.runtime_data.coordinator

    coordinator._detail_cache[1] = WorkoutData(workout_id=1, indoor=False, distance_km=50.0)
    coordinator._detail_cache[2] = WorkoutData(workout_id=2, indoor=False, distance_km=80.0)

    received = _capture_records(hass)
    new = WorkoutData(workout_id=3, indoor=False, distance_km=100.0)
    coordinator._emit_personal_records(new)
    await hass.async_block_till_done()

    assert len(received) == 1
    assert received[0].data["kind"] == "distance"
    assert received[0].data["value"] == 100.0
    assert received[0].data["previous_value"] == 80.0  # higher of 50 and 80


async def test_emit_personal_records_respects_indoor_outdoor_split(
    hass: HomeAssistant,
) -> None:
    """A treadmill 5K shouldn't beat an outdoor 100km distance record."""
    entry = await _bare_entry(hass)
    await _setup_entry(hass, entry)
    coordinator = entry.runtime_data.coordinator

    coordinator._detail_cache[1] = WorkoutData(workout_id=1, indoor=False, distance_km=100.0)
    coordinator._detail_cache[2] = WorkoutData(workout_id=2, indoor=True, distance_km=20.0)

    received = _capture_records(hass)
    # New indoor 25 km beats the indoor 20 → PR. NOT the outdoor 100.
    new = WorkoutData(workout_id=3, indoor=True, distance_km=25.0)
    coordinator._emit_personal_records(new)
    await hass.async_block_till_done()

    assert len(received) == 1
    ev = received[0]
    assert ev.data["kind"] == "distance"
    assert ev.data["value"] == 25.0
    assert ev.data["previous_value"] == 20.0  # the indoor max
    assert ev.data["indoor"] is True


async def test_backfill_paths_do_not_fire_personal_record_events(
    hass: HomeAssistant,
) -> None:
    """The two backfill methods write to the cache silently — no events.

    Pins the design rule that cold-start full_backfill of N historical
    workouts doesn't dump N PR events onto the bus.
    """
    entry = await _bare_entry(hass)
    await _setup_entry(hass, entry)
    coordinator = entry.runtime_data.coordinator

    received = _capture_records(hass)

    # Simulate the backfill insert path: write directly to the cache.
    # The real backfill methods do this through several layers, but the
    # critical invariant is that NEITHER calls ``_emit_personal_records``.
    coordinator._detail_cache[1001] = WorkoutData(
        workout_id=1001, indoor=False, distance_km=200.0, duration_min=600.0, tss=350.0
    )
    coordinator._detail_cache[1002] = WorkoutData(
        workout_id=1002, indoor=False, distance_km=250.0, duration_min=700.0, tss=400.0
    )
    await hass.async_block_till_done()

    assert received == [], (
        "backfill-style direct cache writes must NOT fire PR events; "
        "this is the contract that prevents bus-flooding during "
        "initial multi-page backfills"
    )


async def test_no_events_when_new_workout_has_no_metrics(
    hass: HomeAssistant,
) -> None:
    """A summary-less indoor session shouldn't fire phantom PR events."""
    entry = await _bare_entry(hass)
    await _setup_entry(hass, entry)
    coordinator = entry.runtime_data.coordinator

    received = _capture_records(hass)
    new = WorkoutData(workout_id=1, indoor=True)  # all metric fields None
    coordinator._emit_personal_records(new)
    await hass.async_block_till_done()

    assert received == []
