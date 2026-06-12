"""Regression: detail cache survives schema drift across HA / integration upgrades.

The cache file ``hawahooligan_details_<entry_id>`` carries a
``version`` field, but ``async_load_details_cache`` doesn't gate on
it — the resilience comes from ``workout_data_from_storage`` filtering
unknown keys per entry. That choice is load-bearing for two upgrade
paths:

- Old integration writes v1, new integration reads it: extra default
  fields fill in from the dataclass.
- Future integration writes v2 (more fields), old integration reads
  it: unknown fields are dropped, known fields rehydrate, no crash.

These tests pin both directions plus the corrupted-payload paths.
The whole load path is wrapped in ``except Exception`` so a corrupted
cache must NEVER block setup.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches

_ENTRY_ID = "details-cache-schema-probe"
_DETAILS_STORE_KEY = f"{DOMAIN}_details_{_ENTRY_ID}"


def _entry(hass: HomeAssistant, suffix: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id=f"schema-probe-{suffix}",
        entry_id=_ENTRY_ID,
    )
    entry.add_to_hass(hass)
    return entry


async def _setup_with_seeded_cache(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Boot the entry against a cache that's already on disk."""
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


async def test_future_v2_schema_loads_known_fields_drops_unknowns(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """A future v2 cache file (extra fields) must load — known fields populated, unknowns silently dropped."""
    hass_storage[_DETAILS_STORE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": _DETAILS_STORE_KEY,
        "data": {
            # Future integration bumped the cache schema:
            "version": 2,
            "workouts": {
                "7777": {
                    "workout_id": 7777,
                    "name": "Future-schema ride",
                    "distance_km": 88.8,
                    "power_avg_w": 250.0,
                    # Hypothetical fields a future release adds:
                    "elevation_gain_m": 1200.0,
                    "weather_summary": "sunny",
                    "lap_count": 3,
                }
            },
        },
    }
    entry = _entry(hass, "v2-forward-compat")
    await _setup_with_seeded_cache(hass, entry)

    coordinator = entry.runtime_data.coordinator
    assert 7777 in coordinator._detail_cache
    cached = coordinator._detail_cache[7777]
    # Known fields rehydrate.
    assert cached.name == "Future-schema ride"
    assert cached.distance_km == 88.8
    assert cached.power_avg_w == 250.0
    # Unknown fields can't be retrieved (the WorkoutData dataclass doesn't
    # know about them) — but the load didn't crash, which is the contract.
    assert not hasattr(cached, "elevation_gain_m")


async def test_corrupted_entry_skipped_others_load(hass: HomeAssistant, hass_storage: dict) -> None:
    """One bad entry must not poison the rest of the cache.

    A user filing a bug report about one ride shouldn't lose their entire
    cached history; per-entry isolation in ``async_load_details_cache``
    keeps the rest usable.
    """
    hass_storage[_DETAILS_STORE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": _DETAILS_STORE_KEY,
        "data": {
            "version": 1,
            "workouts": {
                "1000": {  # good
                    "workout_id": 1000,
                    "name": "Good ride",
                    "distance_km": 30.0,
                },
                # Bad: ``name`` field is the wrong type — passes the field
                # filter but the WorkoutData dataclass coerces it to the
                # declared type at access time, not construction; the test
                # just pins that the bogus entry doesn't crash the load.
                "2000": "not even a dict",
                "3000": {  # good
                    "workout_id": 3000,
                    "name": "Another good ride",
                    "distance_km": 40.0,
                },
                # Non-int key:
                "abc": {"workout_id": 4000, "name": "Bad key"},
            },
        },
    }
    entry = _entry(hass, "corrupt-skip")
    await _setup_with_seeded_cache(hass, entry)

    coordinator = entry.runtime_data.coordinator
    # Good entries loaded:
    assert 1000 in coordinator._detail_cache
    assert 3000 in coordinator._detail_cache
    assert coordinator._detail_cache[1000].name == "Good ride"
    # Bad entries did not poison the cache:
    assert 2000 not in coordinator._detail_cache
    # Non-int key never makes it through ``int(wid_str)``:
    assert 4000 not in coordinator._detail_cache


async def test_top_level_workouts_not_a_dict_is_silently_ignored(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Cache file with a corrupt top-level shape must not crash setup."""
    hass_storage[_DETAILS_STORE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": _DETAILS_STORE_KEY,
        "data": {
            "version": 1,
            "workouts": ["not", "a", "dict"],
        },
    }
    entry = _entry(hass, "wrong-shape")
    await _setup_with_seeded_cache(hass, entry)

    coordinator = entry.runtime_data.coordinator
    # The cache load returned early without raising — the dict starts empty.
    assert coordinator._detail_cache == {}


async def test_store_load_raises_does_not_block_setup(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Store I/O exception is caught and warned; setup completes.

    Loss of one cache file must NEVER take down the integration —
    users would lose the picker, totals, and the rest of the
    coordinator stack to a corrupted JSON.
    """
    # Pre-seed valid metadata: an explicit Store.async_load patch raises.
    hass_storage[_DETAILS_STORE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": _DETAILS_STORE_KEY,
        "data": {"version": 1, "workouts": {}},
    }
    entry = _entry(hass, "store-raises")

    real_load_targets = {"calls": 0}

    async def _boom(self) -> None:
        # Only the details cache must blow up; totals/workouts_index must load fine.
        if "_details_" in self.key:
            real_load_targets["calls"] += 1
            raise RuntimeError("simulated disk read failure")
        return None

    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        new=_boom,
    ):
        await _setup_with_seeded_cache(hass, entry)

    assert real_load_targets["calls"] >= 1, "details cache load was not reached"
    coordinator = entry.runtime_data.coordinator
    # Setup completed; the cache is empty because the load was rejected.
    assert coordinator._detail_cache == {}
