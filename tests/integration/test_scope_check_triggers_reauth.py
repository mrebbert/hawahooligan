"""Regression: token-scope check at setup triggers reauth for stale tokens.

Pre-0.7.27 the reauth banner only appeared after an actual 403 from
Wahoo — fine for users who immediately called the new write service,
hostile for everyone else (they upgraded, saw nothing, and the new
service silently 403'd whenever they finally tried it). 0.7.27 closes
the gap by comparing the stored token's granted scopes against the
integration's current ``SCOPES`` constant at setup. A mismatch raises
``ConfigEntryAuthFailed`` → HA's framework shows the reauth banner
immediately.

Two cases to pin:

- Token granted ``power_zones_read`` but ``SCOPES`` now wants
  ``power_zones_write`` too → reauth.
- Token granted everything the constant lists → no reauth, normal
  setup proceeds.

A third (token has no ``scope`` field at all) was the breakage that
caused 0.7.25's reauth banner to be invisible to most users — older
OAuth flows didn't echo the scope. We tolerate that case silently to
avoid re-triggering reauth on healthy restarts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN, SCOPES
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches


def _entry_with_token_scope(hass: HomeAssistant, scope: str | None) -> MockConfigEntry:
    """Build an entry whose stored token carries the given scope string."""
    token: dict = {"access_token": "fake", "refresh_token": "r"}
    if scope is not None:
        token["scope"] = scope
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": token},
        unique_id=f"scope-check-{scope!r}",
    )
    entry.add_to_hass(hass)
    return entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> bool:
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
        return await hass.config_entries.async_setup(entry.entry_id)


async def test_setup_succeeds_when_token_carries_every_current_scope(
    hass: HomeAssistant,
) -> None:
    """Healthy case: token granted everything ``SCOPES`` requires."""
    entry = _entry_with_token_scope(hass, SCOPES)
    assert await _setup(hass, entry)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_setup_triggers_reauth_when_token_missing_a_new_scope(
    hass: HomeAssistant,
) -> None:
    """Pre-0.7.26 token without ``power_zones_write`` → reauth banner."""
    # Simulate an old-token user: granted everything 0.7.25 asked for,
    # but missing the new write scope.
    legacy = "user_read workouts_read power_zones_read offline_data"
    entry = _entry_with_token_scope(hass, legacy)
    await _setup(hass, entry)
    await hass.async_block_till_done()

    # ConfigEntryAuthFailed flips the entry into the SETUP_ERROR state and
    # HA's framework starts a reauth flow — the banner the user wants.
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = list(hass.config_entries.flow.async_progress_by_handler(DOMAIN))
    assert flows, "expected a reauth flow to be in progress"
    assert flows[0]["context"].get("source") == "reauth"


async def test_setup_tolerates_token_without_scope_field(
    hass: HomeAssistant,
) -> None:
    """Older OAuth flows didn't echo the scope — must not re-trigger reauth on healthy restarts."""
    entry = _entry_with_token_scope(hass, None)
    assert await _setup(hass, entry)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    # No active reauth flow even though we don't *know* the scope set.
    flows = list(hass.config_entries.flow.async_progress_by_handler(DOMAIN))
    assert not flows, (
        "no scope field should mean 'trust the token until a 403 says otherwise', "
        "not 'show a reauth banner on every restart'"
    )


@pytest.mark.parametrize(
    "scope_subset",
    [
        "user_read workouts_read",  # missing power_zones_read AND _write
        "user_read workouts_read power_zones_read",  # missing only _write
    ],
)
async def test_partial_missing_scopes_all_trigger_reauth(
    hass: HomeAssistant, scope_subset: str
) -> None:
    """Any subset that doesn't cover SCOPES triggers reauth."""
    entry = _entry_with_token_scope(hass, scope_subset)
    await _setup(hass, entry)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
