"""Regression: ``hawahooligan.set_power_zones`` POSTs / PUTs to Wahoo.

The service bridges the gap that pre-0.7.26 forced users into Postman
for. Contract:

- POST /v1/power_zones when no record exists for the workout_type_id.
- PUT  /v1/power_zones/:id when one does.
- Coggan defaults derived from FTP when zones are omitted; explicit
  ``zone_N`` arguments override per-zone.
- ``async_refresh()`` fires after the write so FTP / Critical Power
  sensors update immediately, without waiting for the daily poll.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches


async def _setup_entry(hass: HomeAssistant, mock_api: MagicMock) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="set-pz-probe",
        entry_id="set-pz-probe",
    )
    entry.add_to_hass(hass)
    with (
        oauth_implementation_patches(),
        patch("custom_components.hawahooligan.WahooApi", return_value=mock_api),
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


@pytest.fixture
def mock_api() -> MagicMock:
    """A WahooApi-shaped mock with the write methods stubbed."""
    api = MagicMock()
    api.async_get_power_zones = AsyncMock(return_value=[])
    api.async_create_power_zones = AsyncMock(return_value={"id": 999})
    api.async_update_power_zones = AsyncMock(return_value={"id": 888})
    return api


async def test_post_when_no_existing_record(hass: HomeAssistant, mock_api: MagicMock) -> None:
    """No record for workout_type_id → POST creates one."""
    await _setup_entry(hass, mock_api)

    with patch(
        "custom_components.hawahooligan.WahooPowerZonesCoordinator.async_refresh",
        new=AsyncMock(),
    ) as refresh:
        await hass.services.async_call(DOMAIN, "set_power_zones", {"ftp": 250}, blocking=True)

    mock_api.async_create_power_zones.assert_awaited_once()
    mock_api.async_update_power_zones.assert_not_called()
    refresh.assert_awaited_once()

    # Payload sanity check.
    payload = mock_api.async_create_power_zones.call_args.args[0]
    assert payload["ftp"] == 250
    assert payload["workout_type_id"] == 0
    assert payload["zone_count"] == 7
    # Coggan defaults landed.
    assert payload["zone_1"] == 138
    assert payload["zone_7"] == 488


async def test_put_when_existing_record_matches_workout_type(
    hass: HomeAssistant, mock_api: MagicMock
) -> None:
    """A record for this workout_type_id → PUT updates it (no second POST)."""
    mock_api.async_get_power_zones = AsyncMock(
        return_value=[
            {"id": 42, "workout_type_id": 0, "ftp": 200},
            # A different workout type that we should NOT touch:
            {"id": 99, "workout_type_id": 2, "ftp": 180},
        ]
    )
    await _setup_entry(hass, mock_api)

    with patch(
        "custom_components.hawahooligan.WahooPowerZonesCoordinator.async_refresh",
        new=AsyncMock(),
    ) as refresh:
        await hass.services.async_call(DOMAIN, "set_power_zones", {"ftp": 260}, blocking=True)

    mock_api.async_update_power_zones.assert_awaited_once()
    mock_api.async_create_power_zones.assert_not_called()
    refresh.assert_awaited_once()

    # Updated the right record id.
    record_id, payload = mock_api.async_update_power_zones.call_args.args
    assert record_id == 42
    assert payload["ftp"] == 260


async def test_explicit_zones_override_coggan_defaults(
    hass: HomeAssistant, mock_api: MagicMock
) -> None:
    """User can pin any subset of zones; the rest fall back to Coggan."""
    await _setup_entry(hass, mock_api)

    await hass.services.async_call(
        DOMAIN,
        "set_power_zones",
        {
            "ftp": 250,
            "zone_4": 270,  # explicit override
            "zone_5": 320,  # explicit override
        },
        blocking=True,
    )
    payload = mock_api.async_create_power_zones.call_args.args[0]
    # Explicit overrides took effect.
    assert payload["zone_4"] == 270
    assert payload["zone_5"] == 320
    # Other zones still come from Coggan derivation.
    assert payload["zone_1"] == 138
    assert payload["zone_7"] == 488


async def test_critical_power_defaults_to_ftp(hass: HomeAssistant, mock_api: MagicMock) -> None:
    """If critical_power isn't passed, mirror FTP."""
    await _setup_entry(hass, mock_api)
    await hass.services.async_call(DOMAIN, "set_power_zones", {"ftp": 250}, blocking=True)
    payload = mock_api.async_create_power_zones.call_args.args[0]
    assert payload["critical_power"] == 250


async def test_payload_uses_int_typed_watts_not_float(
    hass: HomeAssistant, mock_api: MagicMock
) -> None:
    """Wahoo's API rejects float-shaped JSON for power values.

    Pinned after a v0.7.27 user hit ``HTTP 422: Invalid parameter
    'zone_1' value 126.0: Must be a number``. The service must coerce
    every power value to ``int`` before handing it to ``api.async_*``
    so ``json.dumps`` emits ``126`` instead of ``126.0``.
    """
    await _setup_entry(hass, mock_api)
    await hass.services.async_call(
        DOMAIN,
        "set_power_zones",
        {"ftp": 250, "critical_power": 260},
        blocking=True,
    )
    payload = mock_api.async_create_power_zones.call_args.args[0]
    # Strictly int, not float — ``isinstance(True, int)`` is True so the
    # check also guards against ``bool`` slipping through, but no path
    # in the service exposes a bool here.
    for key in ("ftp", "critical_power", *(f"zone_{i}" for i in range(1, 8))):
        assert isinstance(payload[key], int) and not isinstance(payload[key], bool), (
            f"{key} must be int, got {type(payload[key]).__name__} ({payload[key]!r})"
        )


async def test_workout_type_id_routes_to_matching_record(
    hass: HomeAssistant, mock_api: MagicMock
) -> None:
    """An indoor profile (workout_type_id=2) only touches the indoor record.

    Wahoo's API is keyed on (user, workout_type_id) — confusing the two
    would overwrite the user's bike zones with their indoor numbers.
    """
    mock_api.async_get_power_zones = AsyncMock(
        return_value=[
            {"id": 1, "workout_type_id": 0, "ftp": 250},  # bike
            {"id": 2, "workout_type_id": 2, "ftp": 180},  # indoor
        ]
    )
    await _setup_entry(hass, mock_api)

    await hass.services.async_call(
        DOMAIN, "set_power_zones", {"ftp": 200, "workout_type_id": 2}, blocking=True
    )
    record_id, _ = mock_api.async_update_power_zones.call_args.args
    assert record_id == 2  # indoor record id, NOT the bike one
