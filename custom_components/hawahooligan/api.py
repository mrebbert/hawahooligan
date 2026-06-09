"""Async Wahoo Cloud API client.

Wraps the small subset of the Wahoo Cloud API that the integration uses:
authenticated user, workout listing/details, permission deauthorize, and the
FIT-file download.

All REST requests go through ``OAuth2Session.async_request`` so the HA OAuth2
framework handles ``Bearer`` injection and just-in-time token refresh,
including the rotating refresh-token Wahoo issues on every refresh. FIT
downloads bypass the auth layer (CDN URLs are pre-signed and don't count
against rate limits) and only fall back to Bearer if the plain GET returns
401, which would mean the URL has been rotated or the CDN now requires it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientError, ClientResponseError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session

from .const import API_BASE

# Defensive backoff when Wahoo returns 429 — read ``Retry-After`` if present,
# otherwise fall back to a sandbox-safe wait that's longer than the 5-min
# rate-limit window.
_RETRY_AFTER_DEFAULT_SECONDS = 60
_RETRY_AFTER_MAX_SECONDS = 600

_LOGGER = logging.getLogger(__name__)


def _parse_retry_after(header: str | None) -> int:
    """Return seconds to wait for a 429, clamped to a sane range."""
    if header is None:
        return _RETRY_AFTER_DEFAULT_SECONDS
    try:
        value = int(header)
    except (TypeError, ValueError):
        return _RETRY_AFTER_DEFAULT_SECONDS
    if value < 1:
        return _RETRY_AFTER_DEFAULT_SECONDS
    return min(value, _RETRY_AFTER_MAX_SECONDS)


class WahooApiError(Exception):
    """Non-auth Wahoo API failure (network, 5xx, malformed response, …)."""


class WahooApi:
    """Thin async client wired to a HA-managed ``OAuth2Session``."""

    def __init__(self, hass: HomeAssistant, session: OAuth2Session) -> None:
        self._hass = hass
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
        Handles HTTP 429 by sleeping for the ``Retry-After`` window and
        retrying the call once — the budget the backfill layers on top
        keeps healthy callers from ever hitting this branch, but it's a
        useful defensive net when several callers race or the user's
        Wahoo app is on the Sandbox tier.
        """
        url = f"{API_BASE}{path}"
        for attempt in range(2):
            try:
                response = await self._session.async_request(
                    method, url, params=params
                )
            except ClientResponseError as err:
                if err.status in (400, 401):
                    raise ConfigEntryAuthFailed(
                        f"Wahoo refresh failed ({err.status} {err.message})"
                    ) from err
                raise WahooApiError(f"Wahoo API {method} {path} failed: {err}") from err
            except ClientError as err:
                raise WahooApiError(
                    f"Wahoo API {method} {path} transport error: {err}"
                ) from err

            if response.status == 401:
                raise ConfigEntryAuthFailed(
                    "Wahoo API returned 401 — token revoked or expired"
                )
            if response.status == 429 and attempt == 0:
                wait = _parse_retry_after(response.headers.get("Retry-After"))
                _LOGGER.warning(
                    "Wahoo API %s %s returned HTTP 429 — sleeping %ds before retry",
                    method,
                    path,
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            if response.status == 204:
                return None
            if response.status >= 400:
                text = await response.text()
                raise WahooApiError(
                    f"Wahoo API {method} {path} returned HTTP {response.status}: {text[:200]}"
                )

            return await response.json()
        # If both attempts hit 429, surface the second response as a hard
        # failure instead of looping forever.
        raise WahooApiError(
            f"Wahoo API {method} {path} returned HTTP 429 twice in a row"
        )

    async def async_get_user(self) -> dict[str, Any]:
        """Return ``GET /v1/user`` — used as unique_id source for the config entry."""
        return await self._request("GET", "/v1/user")

    async def async_get_workouts(
        self, per_page: int = 1, page: int | None = None
    ) -> dict[str, Any]:
        """Return ``GET /v1/workouts?per_page=N&page=M`` (sorted by ``starts`` desc).

        ``workout_summary`` is frequently ``null`` in the listing — call
        :meth:`async_get_workout` to fetch the full object with the summary.
        Pass ``page`` to paginate beyond the first ``per_page`` workouts
        (full-history backfill); without it Wahoo returns page 1.
        """
        params: dict[str, Any] = {"per_page": per_page}
        if page is not None:
            params["page"] = page
        return await self._request("GET", "/v1/workouts", params=params)

    async def async_get_workout(self, workout_id: int | str) -> dict[str, Any]:
        """Return ``GET /v1/workouts/:id`` (always includes ``workout_summary``)."""
        return await self._request("GET", f"/v1/workouts/{workout_id}")

    async def async_get_power_zones(self) -> list[dict[str, Any]]:
        """Return ``GET /v1/power_zones``.

        Requires the ``power_zones_read`` scope. The base :meth:`_request`
        helper already maps 401 to ``ConfigEntryAuthFailed`` for the
        refresh-token case; here we additionally translate the 403 that
        Wahoo returns when the token genuinely lacks the scope so HA's
        framework triggers the reauth flow.
        """
        try:
            return await self._request("GET", "/v1/power_zones")
        except WahooApiError as err:
            text = str(err)
            if "HTTP 403" in text:
                raise ConfigEntryAuthFailed(
                    "Wahoo /v1/power_zones returned 403 — reauth needed for the "
                    "power_zones_read scope"
                ) from err
            raise

    async def async_delete_permissions(self) -> None:
        """``DELETE /v1/permissions`` — deauthorize the token server-side.

        Called from ``async_remove_entry`` so removing the integration also
        frees one of the user's 10 Wahoo token slots. Best-effort: callers
        should swallow errors so removal never blocks.
        """
        await self._request("DELETE", "/v1/permissions")

    async def async_download_fit(self, url: str) -> bytes | None:
        """Download a FIT file from a ``workout_summary.file.url``.

        Tries the URL anonymously first (CDN-signed; doesn't consume the API
        rate limit). Falls back to Bearer auth on 401, which is the documented
        recovery path for rotated/expired signed URLs. Returns ``None`` on any
        non-auth failure so the caller can skip FIT processing for this poll
        and try again on the next one.
        """
        client = async_get_clientsession(self._hass)
        try:
            async with client.get(url) as response:
                if response.status == 401:
                    _LOGGER.debug("FIT CDN returned 401, retrying with Bearer: %s", url)
                elif response.status >= 400:
                    _LOGGER.warning("FIT download %s returned HTTP %s", url, response.status)
                    return None
                else:
                    return await response.read()
        except ClientError as err:
            _LOGGER.warning("FIT download %s transport error: %s", url, err)
            return None

        # 401 fallback — authenticated retry via OAuth2Session.
        try:
            response = await self._session.async_request("GET", url)
        except ClientResponseError as err:
            if err.status in (400, 401):
                raise ConfigEntryAuthFailed(
                    f"Wahoo FIT auth retry failed ({err.status} {err.message})"
                ) from err
            _LOGGER.warning("FIT download %s authenticated retry failed: %s", url, err)
            return None
        except ClientError as err:
            _LOGGER.warning("FIT download %s authenticated retry transport: %s", url, err)
            return None

        if response.status == 401:
            raise ConfigEntryAuthFailed("Wahoo FIT URL still 401 after Bearer retry")
        if response.status >= 400:
            _LOGGER.warning(
                "FIT download authenticated retry %s returned HTTP %s", url, response.status
            )
            return None
        return await response.read()
