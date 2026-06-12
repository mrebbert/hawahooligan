"""ConfigFlow E2E: OAuth happy path + reauth account-binding.

The ConfigFlow is the only public entry point users have. Its
contract is narrow but load-bearing:

- A fresh install must stamp ``unique_id`` from ``GET /v1/user`` so
  long-term statistics survive token rotation.
- ``/v1/user`` failure must abort with ``cannot_connect`` — never
  silently create an unidentified entry.
- A reauth round-trip must refuse to bind a *different* Wahoo account
  to an existing entry (would corrupt the user's statistics).
- A reauth round-trip with the same account must update the token in
  place — same ``entry_id``, same statistics, fresh token.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow, FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.api import WahooApiError
from custom_components.hawahooligan.config_flow import WahooOAuth2FlowHandler
from custom_components.hawahooligan.const import DOMAIN

_TOKEN = {"access_token": "fresh", "refresh_token": "r", "expires_in": 3600}


def _flow_with_token(hass: HomeAssistant, *, source: str = SOURCE_USER) -> WahooOAuth2FlowHandler:
    """Build a flow handler ready for ``async_oauth_create_entry``."""
    flow = WahooOAuth2FlowHandler()
    flow.hass = hass
    # ``handler`` is what ``_async_current_entries`` keys on; without it
    # the duplicate-unique-id check can't find existing entries.
    flow.handler = DOMAIN
    flow.context = {"source": source}
    return flow


async def test_create_entry_stamps_unique_id_from_wahoo_user_id(hass: HomeAssistant) -> None:
    """Happy path: ``/v1/user`` returns id → entry gets unique_id = str(id)."""
    flow = _flow_with_token(hass)
    api = MagicMock()
    api.async_get_user = AsyncMock(return_value={"id": 4242, "first": "Jane"})

    with patch("custom_components.hawahooligan.config_flow.WahooApi", return_value=api):
        result = await flow.async_oauth_create_entry({"token": _TOKEN})

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "HAWahooligan"
    assert result["data"] == {"token": _TOKEN}
    # The flow stamped the Wahoo user id as the unique_id so a future
    # reauth can confirm it's still the same account.
    assert flow.unique_id == "4242"


async def test_create_entry_aborts_cannot_connect_when_user_api_raises(
    hass: HomeAssistant,
) -> None:
    """``WahooApiError`` from /v1/user → abort, no entry."""
    flow = _flow_with_token(hass)
    api = MagicMock()
    api.async_get_user = AsyncMock(side_effect=WahooApiError("boom"))

    with patch("custom_components.hawahooligan.config_flow.WahooApi", return_value=api):
        result = await flow.async_oauth_create_entry({"token": _TOKEN})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_create_entry_aborts_cannot_connect_when_user_response_has_no_id(
    hass: HomeAssistant,
) -> None:
    """Wahoo returns 200 but payload has no ``id`` → still abort.

    Without the id we have nothing to bind reauth to; a silently-created
    entry could later collide with another account.
    """
    flow = _flow_with_token(hass)
    api = MagicMock()
    api.async_get_user = AsyncMock(return_value={"first": "Jane"})  # no "id"

    with patch("custom_components.hawahooligan.config_flow.WahooApi", return_value=api):
        result = await flow.async_oauth_create_entry({"token": _TOKEN})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_create_entry_aborts_when_unique_id_already_configured(
    hass: HomeAssistant,
) -> None:
    """Re-adding the same Wahoo account through the UI → abort, no duplicate.

    HA's ``_abort_if_unique_id_configured`` handles the abort; we just need
    to confirm the flow checks unique-id BEFORE creating a new entry.
    """
    existing = MockConfigEntry(domain=DOMAIN, unique_id="4242", data={"token": _TOKEN})
    existing.add_to_hass(hass)

    flow = _flow_with_token(hass)
    api = MagicMock()
    api.async_get_user = AsyncMock(return_value={"id": 4242})

    # ``_abort_if_unique_id_configured`` *raises* AbortFlow rather than
    # returning the abort dict — the flow manager catches it in production.
    with (
        patch("custom_components.hawahooligan.config_flow.WahooApi", return_value=api),
        pytest.raises(AbortFlow) as exc_info,
    ):
        await flow.async_oauth_create_entry({"token": _TOKEN})

    assert exc_info.value.reason == "already_configured"


async def test_reauth_same_account_updates_existing_entry(hass: HomeAssistant) -> None:
    """Reauth with the same Wahoo user id → update existing entry, same entry_id."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="4242",
        data={"token": {"access_token": "stale"}},
        entry_id="reauth-same-account",
    )
    existing.add_to_hass(hass)

    flow = _flow_with_token(hass, source=SOURCE_REAUTH)
    # AbstractOAuth2FlowHandler reads the reauth entry id from the flow context.
    flow.context["entry_id"] = existing.entry_id

    api = MagicMock()
    api.async_get_user = AsyncMock(return_value={"id": 4242})

    with (
        patch("custom_components.hawahooligan.config_flow.WahooApi", return_value=api),
        patch.object(hass.config_entries, "async_update_entry", return_value=True) as upd,
        patch.object(hass.config_entries, "async_schedule_reload"),
    ):
        result = await flow.async_oauth_create_entry({"token": _TOKEN})

    assert result["type"] == FlowResultType.ABORT
    # Distinct from the "duplicate add" path — reauth-flavored abort.
    assert result["reason"] == "reauth_successful"
    # The same entry was updated with the fresh token (no new entry created).
    assert upd.called
    # async_update_entry takes the entry positionally or as kwarg; tolerate both.
    args = upd.call_args.args or (upd.call_args.kwargs.get("entry"),)
    assert args[0].entry_id == existing.entry_id


async def test_reauth_wrong_account_aborts_without_updating(hass: HomeAssistant) -> None:
    """Reauth with a different Wahoo user id → abort wrong_account.

    Allowing this would silently rebind statistics to another person's data.
    """
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="4242",
        data={"token": {"access_token": "stale"}},
        entry_id="reauth-wrong-account",
    )
    existing.add_to_hass(hass)

    flow = _flow_with_token(hass, source=SOURCE_REAUTH)
    flow.context["entry_id"] = existing.entry_id

    api = MagicMock()
    # User authorized a DIFFERENT Wahoo account.
    api.async_get_user = AsyncMock(return_value={"id": 9999})

    with (
        patch("custom_components.hawahooligan.config_flow.WahooApi", return_value=api),
        patch.object(hass.config_entries, "async_update_entry") as upd,
    ):
        result = await flow.async_oauth_create_entry({"token": _TOKEN})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    upd.assert_not_called()


async def test_reauth_confirm_shows_form_then_continues_to_user_step(
    hass: HomeAssistant,
) -> None:
    """``async_step_reauth_confirm`` shows a form first, then defers to user step."""
    # ``async_show_form`` reads the reauth entry's title for placeholder
    # interpolation — an actual entry must exist.
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="4242",
        data={"token": {"access_token": "stale"}},
        entry_id="reauth-form-probe",
        title="HAWahooligan",
    )
    existing.add_to_hass(hass)

    flow = _flow_with_token(hass, source=SOURCE_REAUTH)
    flow.context["entry_id"] = existing.entry_id

    # First call (no input) → form.
    result = await flow.async_step_reauth_confirm()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    # Second call (with input) → defers to async_step_user, which would
    # normally redirect to the OAuth authorize URL. We only need to confirm
    # the form-input branch hands off and doesn't reabort.
    with patch.object(
        flow, "async_step_user", new=AsyncMock(return_value={"type": FlowResultType.EXTERNAL_STEP})
    ) as user_step:
        await flow.async_step_reauth_confirm({})
    user_step.assert_awaited_once()


@pytest.mark.parametrize("scope_payload", [None, {"scope": "wrong"}])
async def test_extra_authorize_data_requests_the_integration_scopes(
    hass: HomeAssistant, scope_payload: dict | None
) -> None:
    """``extra_authorize_data`` must request the project's full scope list.

    Dropping ``power_zones_read`` here is what caused the 0.7.3 reauth
    storm for pre-existing entries; the parametrize ignores caller-side
    state and pins the flow's own contract.
    """
    flow = _flow_with_token(hass)
    extra = flow.extra_authorize_data
    assert "scope" in extra
    # SCOPES is a space-joined string; just confirm the read scope is in there.
    assert "workouts_read" in extra["scope"]
    assert "power_zones_read" in extra["scope"]
    # Argument is unused — exists so parametrize exercises the property twice
    # under different surrounding conditions without test duplication.
    _ = scope_payload
