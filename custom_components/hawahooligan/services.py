"""HA services for HAWahooligan.

``hawahooligan.render_workout``
  On-demand: fetch a specific Wahoo workout by id and render its FIT file to
  ``<config>/www/hawahooligan/<id>.geojson``. Used to backfill historic
  rides older than the first-setup window or to re-render a track after a
  viewer / parsing change.

``hawahooligan.select_workout``
  Pin the headline sensors and map viewer to a specific workout id. Pass
  ``workout_id: latest`` (or ``null``) to release the pin and follow the
  newest workout again. Used by the bundled viewer dropdown so picking a
  ride from the map also updates the sensor cards next to it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import (
    DOMAIN,
    FULL_BACKFILL_DEFAULT_BUDGET,
    FULL_BACKFILL_DEFAULT_WINDOW_SECONDS,
    FULL_BACKFILL_MAX_PAGES,
    SERVICE_FULL_BACKFILL,
    SERVICE_RENDER_WORKOUT,
    SERVICE_SELECT_WORKOUT,
)

if TYPE_CHECKING:
    from . import HawahooliganConfigEntry

_LOGGER = logging.getLogger(__name__)

_ATTR_WORKOUT_ID = "workout_id"
_ATTR_CONFIG_ENTRY_ID = "config_entry_id"
_ATTR_FORCE = "force"
_ATTR_WITH_TRACKS = "with_tracks"
_ATTR_MAX_PAGES = "max_pages"
_ATTR_MAX_CALLS_PER_WINDOW = "max_calls_per_window"
_ATTR_WINDOW_SECONDS = "window_seconds"

_RENDER_SCHEMA = vol.Schema(
    {
        vol.Required(_ATTR_WORKOUT_ID): vol.Any(vol.Coerce(int), str),
        vol.Optional(_ATTR_CONFIG_ENTRY_ID): str,
        vol.Optional(_ATTR_FORCE, default=False): bool,
    }
)


def _coerce_select_workout_id(value: object) -> int | None:
    """Accept ``"latest"`` / ``""`` / ``None`` as the "follow latest" sentinel."""
    if value is None:
        return None
    if isinstance(value, str):
        if value.strip().lower() in {"", "latest", "null", "none"}:
            return None
        try:
            return int(value)
        except ValueError as err:
            raise vol.Invalid(f"workout_id must be an integer or 'latest', got {value!r}") from err
    if isinstance(value, bool):
        # voluptuous coerces bool to int; reject explicitly so True doesn't
        # silently become workout_id=1.
        raise vol.Invalid("workout_id must be an integer or 'latest'")
    if isinstance(value, int):
        return value
    raise vol.Invalid(f"workout_id must be an integer or 'latest', got {type(value).__name__}")


_SELECT_SCHEMA = vol.Schema(
    {
        vol.Optional(_ATTR_WORKOUT_ID, default=None): _coerce_select_workout_id,
        vol.Optional(_ATTR_CONFIG_ENTRY_ID): str,
    }
)

_FULL_BACKFILL_SCHEMA = vol.Schema(
    {
        vol.Optional(_ATTR_WITH_TRACKS, default=False): bool,
        vol.Optional(_ATTR_MAX_PAGES, default=FULL_BACKFILL_MAX_PAGES): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=1000)
        ),
        vol.Optional(_ATTR_MAX_CALLS_PER_WINDOW, default=FULL_BACKFILL_DEFAULT_BUDGET): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=200)
        ),
        vol.Optional(_ATTR_WINDOW_SECONDS, default=FULL_BACKFILL_DEFAULT_WINDOW_SECONDS): vol.All(
            vol.Coerce(float), vol.Range(min=10.0, max=3600.0)
        ),
        vol.Optional(_ATTR_CONFIG_ENTRY_ID): str,
    }
)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register HAWahooligan services once per Home Assistant instance."""
    if not hass.services.has_service(DOMAIN, SERVICE_RENDER_WORKOUT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RENDER_WORKOUT,
            _handle_render_workout,
            schema=_RENDER_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SELECT_WORKOUT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SELECT_WORKOUT,
            _handle_select_workout,
            schema=_SELECT_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_FULL_BACKFILL):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FULL_BACKFILL,
            _handle_full_backfill,
            schema=_FULL_BACKFILL_SCHEMA,
        )


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove HAWahooligan services when the last entry unloads."""
    for service in (
        SERVICE_RENDER_WORKOUT,
        SERVICE_SELECT_WORKOUT,
        SERVICE_FULL_BACKFILL,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


async def _handle_render_workout(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call.hass, call.data.get(_ATTR_CONFIG_ENTRY_ID))
    workout_id = call.data[_ATTR_WORKOUT_ID]
    force = bool(call.data.get(_ATTR_FORCE, False))
    try:
        url = await coordinator.async_render_workout(workout_id, force=force)
    except HomeAssistantError:
        raise
    except Exception as err:  # noqa: BLE001 — surface as ServiceValidationError
        raise HomeAssistantError(f"Rendering workout {workout_id} failed: {err}") from err
    if url is None:
        _LOGGER.info(
            "render_workout: workout %s has no renderable track (indoor/manual/no GPS)",
            workout_id,
        )
    else:
        _LOGGER.info("render_workout: %s → %s", workout_id, url)


async def _handle_select_workout(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call.hass, call.data.get(_ATTR_CONFIG_ENTRY_ID))
    workout_id = call.data.get(_ATTR_WORKOUT_ID)
    try:
        await coordinator.async_select_workout(workout_id)
    except HomeAssistantError:
        raise
    except Exception as err:  # noqa: BLE001 — surface as HomeAssistantError
        raise HomeAssistantError(f"Selecting workout {workout_id} failed: {err}") from err
    _LOGGER.info(
        "select_workout: pin set to %s",
        "latest" if workout_id is None else workout_id,
    )


async def _handle_full_backfill(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call.hass, call.data.get(_ATTR_CONFIG_ENTRY_ID))
    with_tracks = bool(call.data.get(_ATTR_WITH_TRACKS, False))
    max_pages = int(call.data.get(_ATTR_MAX_PAGES, FULL_BACKFILL_MAX_PAGES))
    max_calls_per_window = int(
        call.data.get(_ATTR_MAX_CALLS_PER_WINDOW, FULL_BACKFILL_DEFAULT_BUDGET)
    )
    window_seconds = float(
        call.data.get(_ATTR_WINDOW_SECONDS, FULL_BACKFILL_DEFAULT_WINDOW_SECONDS)
    )

    async def _run() -> None:
        try:
            added = await coordinator.async_full_backfill(
                with_tracks=with_tracks,
                max_pages=max_pages,
                max_calls_per_window=max_calls_per_window,
                window_seconds=window_seconds,
            )
        except Exception as err:  # noqa: BLE001 — backfill must not crash HA
            _LOGGER.warning("Full backfill aborted: %s", err)
            return
        _LOGGER.info("Full backfill finished: %d new workouts recorded", added)

    # The loop can take minutes to hours on rate-limited tiers, so fire-and-
    # forget: the service call returns immediately and progress flows through
    # the EVENT_BACKFILL_PROGRESS bus event + log messages.
    call.hass.async_create_background_task(_run(), name="hawahooligan_full_backfill")
    _LOGGER.info(
        "full_backfill: kicked off (with_tracks=%s, budget=%d / %.0fs)",
        with_tracks,
        max_calls_per_window,
        window_seconds,
    )


def _resolve_coordinator(hass: HomeAssistant, entry_id: str | None):
    """Locate a loaded HAWahooligan coordinator.

    With a single configured account (the common case) callers can omit
    ``config_entry_id``; with multiple accounts we require the caller to be
    explicit so we don't render to the wrong account's directory.
    """
    entries: list[HawahooliganConfigEntry] = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if not entries:
        raise ServiceValidationError("HAWahooligan is not loaded — set up the integration first.")

    if entry_id is None:
        if len(entries) > 1:
            raise ServiceValidationError(
                "Multiple HAWahooligan accounts configured — set `config_entry_id` to pick one."
            )
        entry = entries[0]
    else:
        matching = [e for e in entries if e.entry_id == entry_id]
        if not matching:
            raise ServiceValidationError(
                f"No loaded HAWahooligan config entry with id {entry_id!r}"
            )
        entry = matching[0]

    return entry.runtime_data.coordinator
