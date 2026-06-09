"""Regression: ``async_load_totals`` runs during setup, not just gets defined.

Background: Phase 4 v1 shipped lifetime totals with persistence — but
``__init__.async_setup_entry`` never called ``coordinator.async_load_totals()``,
so every HA restart silently reset the totals to zero. The drive-by
fix in 0.7.4 wired the call in. This test pre-seeds the totals Store
and asserts the coordinator picks them up at setup time. If the load
call ever gets dropped or moved, the coordinator's totals stay empty
and the assertion fails.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData
from custom_components.hawahooligan.totals import SCHEMA_VERSION

from ._setup import oauth_implementation_patches

# Known entry_id pins the Store key (`{DOMAIN}_totals_{entry_id}`) so
# the pre-seeded payload lands where async_load_totals will look.
_ENTRY_ID = "totals-wiring-probe"
_STORE_KEY = f"{DOMAIN}_totals_{_ENTRY_ID}"


async def test_async_load_totals_rehydrates_at_setup(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    # Pre-seed HA's storage with a totals payload from a notional prior
    # run. Three workouts spanning indoor + outdoor + legacy (no flag).
    hass_storage[_STORE_KEY] = {
        "version": SCHEMA_VERSION,
        "minor_version": 1,
        "key": _STORE_KEY,
        "data": {
            "version": SCHEMA_VERSION,
            "workouts": {
                "100": {
                    "distance_km": 42.0,
                    "ascent_m": 250.0,
                    "duration_min": 90.0,
                    "calories_kcal": 800.0,
                    "work_kj": 1200.0,
                    "tss": 75.0,
                    "indoor": False,
                },
                "101": {
                    "distance_km": 18.0,
                    "ascent_m": 0.0,
                    "duration_min": 45.0,
                    "calories_kcal": 350.0,
                    "work_kj": 500.0,
                    "tss": 40.0,
                    "indoor": True,
                },
                # Legacy entry persisted before the indoor split landed
                # (no ``indoor`` key). Must still count toward totals but
                # not toward either subset.
                "102": {
                    "distance_km": 30.0,
                    "duration_min": 60.0,
                },
            },
        },
    }

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="totals-wiring-probe-unique",
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
        # Skip the backfill background task — the listing mock would
        # otherwise add a 4th workout to the totals.
        patch(
            "custom_components.hawahooligan.WahooCoordinator.async_backfill_recent",
            new=AsyncMock(return_value=0),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    totals = coordinator.totals

    # If ``async_load_totals`` never ran the coordinator's ``_totals`` is
    # the default empty ``LifetimeTotals()`` — workout_count == 0.
    assert totals.workout_count == 3, (
        f"expected 3 workouts loaded from store, got {totals.workout_count}. "
        f"async_load_totals likely no longer runs during setup."
    )

    # Outdoor/indoor split survives the roundtrip (covers totals.py and the
    # storage adapter — but the wiring assertion above is the load-bearing
    # one).
    assert totals.workout_count_outdoor == 1
    assert totals.workout_count_indoor == 1
    assert totals.distance_km == 90.0  # 42 + 18 + 30
    assert totals.sum("distance_km", indoor=False) == 42.0
    assert totals.sum("distance_km", indoor=True) == 18.0
