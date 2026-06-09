"""Regression: ``hawahooligan.cleanup_geojson`` deletes only stale tracks.

Covers the new service end-to-end — service registration, schema
defaults, coordinator dispatch, filesystem effect. Pre-populates the
cache dir with two old + two fresh files and asserts only the old ones
disappear.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN, WWW_SUBPATH
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches

_OLD_DAYS = 200  # well past the default 180-day threshold
_FRESH_DAYS = 5
_SECONDS_PER_DAY = 86400


def _stamp(path: Path, age_days: int) -> None:
    """Set mtime/atime to ``age_days`` (+1 min) ago via os.utime.

    The extra minute keeps us clear of races where ``cutoff_epoch`` lands
    exactly on the file's mtime.
    """
    target = path.stat().st_mtime - age_days * _SECONDS_PER_DAY - 60
    os.utime(path, (target, target))


async def _setup_and_get_dir(hass: HomeAssistant) -> tuple[MockConfigEntry, Path]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="cleanup-probe",
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

    geojson_dir = Path(hass.config.path(*WWW_SUBPATH))
    geojson_dir.mkdir(parents=True, exist_ok=True)
    return entry, geojson_dir


async def test_cleanup_geojson_service_removes_only_old_files(hass: HomeAssistant) -> None:
    entry, geojson_dir = await _setup_and_get_dir(hass)

    # Two stale files, two fresh ones. Different ids so the test fails
    # clearly if the wrong file ends up removed.
    old_a = geojson_dir / "1001.geojson"
    old_b = geojson_dir / "1002.geojson"
    fresh_a = geojson_dir / "2001.geojson"
    fresh_b = geojson_dir / "2002.geojson"
    for path in (old_a, old_b, fresh_a, fresh_b):
        path.write_text("{}", encoding="utf-8")
    _stamp(old_a, _OLD_DAYS)
    _stamp(old_b, _OLD_DAYS)
    _stamp(fresh_a, _FRESH_DAYS)
    _stamp(fresh_b, _FRESH_DAYS)

    await hass.services.async_call(
        DOMAIN,
        "cleanup_geojson",
        {"max_age_days": 180, "config_entry_id": entry.entry_id},
        blocking=True,
    )

    assert not old_a.exists(), "200-day-old file should be removed"
    assert not old_b.exists(), "200-day-old file should be removed"
    assert fresh_a.exists(), "5-day-old file must survive the 180-day cutoff"
    assert fresh_b.exists(), "5-day-old file must survive the 180-day cutoff"


async def test_cleanup_geojson_service_uses_default_age_when_unset(
    hass: HomeAssistant,
) -> None:
    """Omitting ``max_age_days`` falls back to the 180-day default."""
    entry, geojson_dir = await _setup_and_get_dir(hass)

    stale = geojson_dir / "3001.geojson"
    fresh = geojson_dir / "3002.geojson"
    for path in (stale, fresh):
        path.write_text("{}", encoding="utf-8")
    _stamp(stale, 365)  # one year old
    _stamp(fresh, 30)  # one month old

    await hass.services.async_call(
        DOMAIN,
        "cleanup_geojson",
        {"config_entry_id": entry.entry_id},
        blocking=True,
    )

    assert not stale.exists()
    assert fresh.exists()


async def test_cleanup_geojson_service_handles_empty_dir(hass: HomeAssistant) -> None:
    """A cleanup against an empty cache must not raise."""
    entry, _ = await _setup_and_get_dir(hass)
    await hass.services.async_call(
        DOMAIN,
        "cleanup_geojson",
        {"config_entry_id": entry.entry_id},
        blocking=True,
    )
