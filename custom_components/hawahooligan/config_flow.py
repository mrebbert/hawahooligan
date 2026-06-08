"""Config flow for HAWahooligan.

Drives the OAuth2 auth-code grant with Wahoo Cloud via the HA framework's
``AbstractOAuth2FlowHandler``. The fresh token is used immediately to call
``GET /v1/user`` so we can stamp the Wahoo user id as the entry's unique_id —
which makes reauth resilient to account swaps (a different Wahoo account
cannot accidentally take over the entry and corrupt long-term statistics).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .api import WahooApi, WahooApiError
from .const import API_BASE, DOMAIN, SCOPES

_LOGGER = logging.getLogger(__name__)


class WahooOAuth2FlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Handle the OAuth2 flow for Wahoo Cloud."""

    DOMAIN = DOMAIN
    VERSION = 1

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Request the read-only scopes the integration needs."""
        return {"scope": SCOPES}

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Token rotation failed (or the user revoked the app) — re-auth."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm before kicking off another OAuth round-trip."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Finalize the flow: stamp ``unique_id`` from ``/v1/user`` and persist.

        Initial and reauth flows share the same code path: we always identify
        the Wahoo account first, then either create a new entry or update the
        existing one (preserving entry_id and long-term statistics).
        """
        api = WahooApi(_PreEntryOAuthSession(self.hass, data))
        try:
            user = await api.async_get_user()
        except WahooApiError as err:
            _LOGGER.warning("Wahoo /v1/user failed during config flow: %s", err)
            return self.async_abort(reason="cannot_connect")

        user_id = user.get("id")
        if user_id is None:
            _LOGGER.warning("Wahoo /v1/user returned no id field: %s", user)
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(str(user_id))

        if self.source == SOURCE_REAUTH:
            reauth_entry = self._get_reauth_entry()
            if reauth_entry.unique_id != str(user_id):
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(reauth_entry, data=data)

        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="HAWahooligan", data=data)


class _PreEntryOAuthSession:
    """Minimal ``OAuth2Session``-shaped object for the ``/v1/user`` probe.

    We need to call the Wahoo API with the fresh token *before* a ConfigEntry
    exists, so we cannot use the real ``OAuth2Session`` (it requires an entry).
    This shim mirrors the two methods :class:`WahooApi` uses on a session.
    """

    def __init__(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        self._hass = hass
        self._data = data

    @property
    def token(self) -> dict[str, Any]:
        return self._data["token"]

    async def async_ensure_token_valid(self) -> None:
        # Token is fresh out of the authorize step — no refresh needed.
        return None

    async def async_request(self, method: str, url: str, **kwargs: Any) -> Any:
        # Wahoo paths in :class:`WahooApi` are prefixed with the API base; the
        # helper expects a full URL, which it already is.
        assert url.startswith(API_BASE), url
        return await config_entry_oauth2_flow.async_oauth2_request(
            self._hass, self._data["token"], method, url, **kwargs
        )
