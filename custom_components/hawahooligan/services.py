"""HA services for HAWahooligan.

``hawahooligan.render_workout``
  On-demand: fetch a specific Wahoo workout by id, render its FIT file to
  ``<config>/www/hawahooligan/<id>.geojson``, and refresh ``latest.geojson``
  if the call's ``set_as_latest`` argument is true.

Used to backfill historic rides older than the first-setup window or to
re-render a track after a viewer / parsing change.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN, SERVICE_RENDER_WORKOUT

if TYPE_CHECKING:
    from . import HawahooliganConfigEntry

_LOGGER = logging.getLogger(__name__)

_ATTR_WORKOUT_ID = "workout_id"
_ATTR_CONFIG_ENTRY_ID = "config_entry_id"
_ATTR_FORCE = "force"

_RENDER_SCHEMA = vol.Schema(
    {
        vol.Required(_ATTR_WORKOUT_ID): vol.Any(vol.Coerce(int), str),
        vol.Optional(_ATTR_CONFIG_ENTRY_ID): str,
        vol.Optional(_ATTR_FORCE, default=False): bool,
    }
)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register HAWahooligan services once per Home Assistant instance."""
    if hass.services.has_service(DOMAIN, SERVICE_RENDER_WORKOUT):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_RENDER_WORKOUT,
        _handle_render_workout,
        schema=_RENDER_SCHEMA,
    )


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove HAWahooligan services when the last entry unloads."""
    if hass.services.has_service(DOMAIN, SERVICE_RENDER_WORKOUT):
        hass.services.async_remove(DOMAIN, SERVICE_RENDER_WORKOUT)


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
