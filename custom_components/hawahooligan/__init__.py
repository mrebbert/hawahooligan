"""The HAWahooligan integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .api import WahooApi
from .const import PLATFORMS
from .coordinator import WahooCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class HawahooliganData:
    """Runtime data attached to the config entry."""

    api: WahooApi
    coordinator: WahooCoordinator


type HawahooliganConfigEntry = ConfigEntry[HawahooliganData]


async def async_setup_entry(hass: HomeAssistant, entry: HawahooliganConfigEntry) -> bool:
    """Set up HAWahooligan from a config entry."""
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
        hass, entry
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    api = WahooApi(session)
    coordinator = WahooCoordinator(hass, entry, api)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = HawahooliganData(api=api, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HawahooliganConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: HawahooliganConfigEntry) -> None:
    """Deauthorize the Wahoo token when the integration is removed.

    Best-effort: any failure is logged and swallowed so the removal flow itself
    never blocks. Releases one of the user's 10 Wahoo token slots.
    """
    try:
        implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
        session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
        api = WahooApi(session)
        await api.async_delete_permissions()
    except Exception as err:  # noqa: BLE001 — best-effort deauth, never block removal
        _LOGGER.warning("Wahoo DELETE /v1/permissions on entry removal failed: %s", err)
