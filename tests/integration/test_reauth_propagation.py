"""Regression: power-zones first-refresh ``ConfigEntryAuthFailed`` triggers reauth.

Background: 0.7.3 fixed a bug where ``except Exception`` in
``async_setup_entry`` swallowed ``ConfigEntryAuthFailed`` from the
power-zones coordinator. Users adding the integration before 0.7.3 had
the ``power_zones_read`` scope added in a later release and never saw
the reauth banner that should have prompted them to re-authorize. This
test pins the explicit-catch path so a future refactor can't quietly
re-broaden the except clause.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN

from ._setup import oauth_implementation_patches


async def test_power_zones_auth_failure_triggers_reauth(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="reauth-propagation-probe",
    )
    entry.add_to_hass(hass)

    with (
        oauth_implementation_patches(),
        patch("custom_components.hawahooligan.WahooApi", return_value=MagicMock()),
        patch(
            "custom_components.hawahooligan.WahooCoordinator.async_config_entry_first_refresh",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.hawahooligan.WahooCoordinator.async_backfill_recent",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "custom_components.hawahooligan.WahooPowerZonesCoordinator.async_config_entry_first_refresh",
            new=AsyncMock(side_effect=ConfigEntryAuthFailed("power_zones_read scope missing")),
        ),
        patch.object(MockConfigEntry, "async_start_reauth", autospec=True) as reauth_spy,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # ``async_start_reauth`` is called once and only once: the explicit
    # ``except ConfigEntryAuthFailed`` branch in ``__init__.py``.
    assert reauth_spy.call_count == 1, (
        f"expected exactly one async_start_reauth call, got {reauth_spy.call_count}"
    )
    # Sanity: the call is bound to OUR entry, not some HA-internal probe entry.
    called_entry, _hass = reauth_spy.call_args.args
    assert called_entry is entry


async def test_power_zones_non_auth_failure_does_not_trigger_reauth(
    hass: HomeAssistant,
) -> None:
    """Generic failures must stay advisory — no reauth banner, no setup abort."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="reauth-non-auth-probe",
    )
    entry.add_to_hass(hass)

    with (
        oauth_implementation_patches(),
        patch("custom_components.hawahooligan.WahooApi", return_value=MagicMock()),
        patch(
            "custom_components.hawahooligan.WahooCoordinator.async_config_entry_first_refresh",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.hawahooligan.WahooCoordinator.async_backfill_recent",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "custom_components.hawahooligan.WahooPowerZonesCoordinator.async_config_entry_first_refresh",
            new=AsyncMock(side_effect=RuntimeError("transient network blip")),
        ),
        patch.object(MockConfigEntry, "async_start_reauth", autospec=True) as reauth_spy,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert reauth_spy.call_count == 0, (
        "non-auth failure must not start a reauth flow — would burn the "
        "user's reauth UX on transient errors"
    )
