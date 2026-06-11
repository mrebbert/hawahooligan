"""Regression: ``hawahooligan.select_workout`` dispatches to the coordinator.

Pins the service → coordinator wiring plus the special-case parsing of
the "latest" sentinel. Catches a future refactor that breaks any of:
schema validation, ``config_entry_id`` routing, or the call to
``coordinator.async_select_workout``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="select-workout-probe",
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


async def test_select_workout_dispatches_numeric_id(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator

    with patch.object(coordinator, "async_select_workout", new=AsyncMock()) as select_spy:
        await hass.services.async_call(
            DOMAIN,
            "select_workout",
            {"workout_id": 12345, "config_entry_id": entry.entry_id},
            blocking=True,
        )

    select_spy.assert_awaited_once_with(12345)


async def test_select_workout_dispatches_latest_sentinel(hass: HomeAssistant) -> None:
    """The "latest" string in service data must collapse to ``None``."""
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator

    with patch.object(coordinator, "async_select_workout", new=AsyncMock()) as select_spy:
        await hass.services.async_call(
            DOMAIN,
            "select_workout",
            {"workout_id": "latest", "config_entry_id": entry.entry_id},
            blocking=True,
        )

    select_spy.assert_awaited_once_with(None)


async def test_select_workout_accepts_string_id(hass: HomeAssistant) -> None:
    """HA service-call payloads stringify integers; ensure ``"42"`` → ``42``."""
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator

    with patch.object(coordinator, "async_select_workout", new=AsyncMock()) as select_spy:
        await hass.services.async_call(
            DOMAIN,
            "select_workout",
            {"workout_id": "42", "config_entry_id": entry.entry_id},
            blocking=True,
        )

    select_spy.assert_awaited_once_with(42)


async def test_select_workout_rejects_garbage(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)
    with pytest.raises((ServiceValidationError, Exception)):
        await hass.services.async_call(
            DOMAIN,
            "select_workout",
            {"workout_id": "definitely-not-an-id", "config_entry_id": entry.entry_id},
            blocking=True,
        )


async def test_select_workout_writes_selected_id_synchronously(
    hass: HomeAssistant,
) -> None:
    """Pin lands in workouts.json before async_request_refresh fires.

    Regression for the v0.7.12 bug where the iframe viewer lagged the
    sensors by 10-15 s because manifest.selected_id only got rewritten
    on the next DataUpdateCoordinator cycle.
    """
    import json
    from pathlib import Path

    from custom_components.hawahooligan.const import MANIFEST_FILENAME, WWW_SUBPATH

    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data.coordinator

    # Spy on request_refresh so we can prove the manifest was written
    # before HA was even asked to refresh.
    refresh_calls: list[None] = []

    async def _record_request_refresh() -> None:
        manifest_path = Path(hass.config.path(*WWW_SUBPATH)) / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise AssertionError("manifest must exist by the time async_request_refresh fires")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        # The pinned id must already be on disk.
        if payload.get("selected_id") != 12345:
            raise AssertionError(
                f"manifest.selected_id is {payload.get('selected_id')!r}, "
                "expected 12345 — manifest was not written synchronously"
            )
        refresh_calls.append(None)

    with patch.object(coordinator, "async_request_refresh", new=_record_request_refresh):
        await hass.services.async_call(
            DOMAIN,
            "select_workout",
            {"workout_id": 12345, "config_entry_id": entry.entry_id},
            blocking=True,
        )

    assert refresh_calls == [None], "async_request_refresh should fire exactly once"
