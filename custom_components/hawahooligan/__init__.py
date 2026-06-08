"""The HAWahooligan integration."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .api import WahooApi
from .const import DOMAIN, PLATFORMS, WWW_SUBPATH
from .coordinator import WahooCoordinator
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

_PACKAGED_MAP_HTML = Path(__file__).parent / "web" / "map.html"
_VIEWER_VERSION_RE = re.compile(r"HAWahooligan-Viewer-Version:\s*(\d+)")


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
    api = WahooApi(hass, session)
    coordinator = WahooCoordinator(hass, entry, api)

    await hass.async_add_executor_job(_provision_viewer, Path(hass.config.path(*WWW_SUBPATH)))

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = HawahooliganData(api=api, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async_register_services(hass)

    # Backfill historic tracks in the background so setup never blocks on N
    # FIT downloads. Idempotent — already-rendered workouts are skipped.
    entry.async_create_background_task(
        hass,
        _backfill(coordinator),
        name="hawahooligan_backfill",
    )
    return True


async def _backfill(coordinator: WahooCoordinator) -> None:
    try:
        rendered = await coordinator.async_backfill_recent()
    except Exception as err:  # noqa: BLE001 — backfill never blocks setup
        _LOGGER.warning("HAWahooligan backfill failed: %s", err)
        return
    if rendered:
        _LOGGER.info("HAWahooligan backfilled %d historic track(s)", rendered)


async def async_unload_entry(hass: HomeAssistant, entry: HawahooliganConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not hass.config_entries.async_loaded_entries(DOMAIN):
        async_unregister_services(hass)
    return unloaded


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
        api = WahooApi(hass, session)
        await api.async_delete_permissions()
    except Exception as err:  # noqa: BLE001 — best-effort deauth, never block removal
        _LOGGER.warning("Wahoo DELETE /v1/permissions on entry removal failed: %s", err)


def _provision_viewer(target_dir: Path) -> None:
    """Drop the packaged ``map.html`` into ``<config>/www/hawahooligan/``.

    Re-installs when the packaged ``HAWahooligan-Viewer-Version`` is higher
    than what's already in the target file. If the user has deleted that
    version marker from their copy (intentional pin), the file is left alone.

    Best-effort: any IO failure is logged and swallowed — the integration
    still works, just without the map viewer until the next restart.
    """
    try:
        if not _PACKAGED_MAP_HTML.is_file():
            _LOGGER.debug("Packaged map.html missing — skipping viewer provisioning")
            return
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "map.html"
        packaged_version = _extract_viewer_version(_PACKAGED_MAP_HTML.read_text("utf-8"))
        if target.exists():
            existing_version = _extract_viewer_version(target.read_text("utf-8"))
            if existing_version is None:
                _LOGGER.debug("Existing map.html has no version marker — leaving it alone")
                return
            if packaged_version is not None and existing_version >= packaged_version:
                return
        shutil.copyfile(_PACKAGED_MAP_HTML, target)
        _LOGGER.info("Provisioned HAWahooligan map viewer at %s", target)
    except OSError as err:
        _LOGGER.warning("Could not provision map.html: %s", err)


def _extract_viewer_version(content: str) -> int | None:
    match = _VIEWER_VERSION_RE.search(content)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None
