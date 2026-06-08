"""Async Wahoo Cloud API client.

Wraps the small subset of the Wahoo Cloud API that the integration uses:
authenticated user, workout listing/details, and permission deauthorize.

All requests go through ``OAuth2Session.async_request`` so the HA OAuth2
framework handles ``Bearer`` injection and just-in-time token refresh,
including the rotating refresh-token Wahoo issues on every refresh.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError, ClientResponseError
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)


class WahooApiError(Exception):
    """Non-auth Wahoo API failure (network, 5xx, malformed response, …)."""


class WahooApi:
    """Thin async client wired to a HA-managed ``OAuth2Session``."""

    def __init__(self, session: OAuth2Session) -> None:
        self._session = session

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Perform an authenticated request and decode the JSON body.

        Maps HTTP 401 / invalid_grant to ``ConfigEntryAuthFailed`` so the
        coordinator can trigger the reauth flow without losing the entry.
        """
        url = f"{API_BASE}{path}"
        try:
            response = await self._session.async_request(method, url, params=params)
        except ClientResponseError as err:
            if err.status in (400, 401):
                raise ConfigEntryAuthFailed(
                    f"Wahoo refresh failed ({err.status} {err.message})"
                ) from err
            raise WahooApiError(f"Wahoo API {method} {path} failed: {err}") from err
        except ClientError as err:
            raise WahooApiError(f"Wahoo API {method} {path} transport error: {err}") from err

        if response.status == 401:
            raise ConfigEntryAuthFailed("Wahoo API returned 401 — token revoked or expired")
        if response.status == 204:
            return None
        if response.status >= 400:
            text = await response.text()
            raise WahooApiError(
                f"Wahoo API {method} {path} returned HTTP {response.status}: {text[:200]}"
            )

        return await response.json()

    async def async_get_user(self) -> dict[str, Any]:
        """Return ``GET /v1/user`` — used as unique_id source for the config entry."""
        return await self._request("GET", "/v1/user")

    async def async_get_workouts(self, per_page: int = 1) -> dict[str, Any]:
        """Return ``GET /v1/workouts?per_page=N`` (sorted by ``starts`` desc).

        ``workout_summary`` is frequently ``null`` in the listing — call
        :meth:`async_get_workout` to fetch the full object with the summary.
        """
        return await self._request("GET", "/v1/workouts", params={"per_page": per_page})

    async def async_get_workout(self, workout_id: int | str) -> dict[str, Any]:
        """Return ``GET /v1/workouts/:id`` (always includes ``workout_summary``)."""
        return await self._request("GET", f"/v1/workouts/{workout_id}")

    async def async_delete_permissions(self) -> None:
        """``DELETE /v1/permissions`` — deauthorize the token server-side.

        Called from ``async_remove_entry`` so removing the integration also
        frees one of the user's 10 Wahoo token slots. Best-effort: callers
        should swallow errors so removal never blocks.
        """
        await self._request("DELETE", "/v1/permissions")
