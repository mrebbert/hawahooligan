"""The HAWahooligan integration."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow

from .api import WahooApi
from .const import DOMAIN, PLATFORMS, SCOPES, WWW_SUBPATH
from .coordinator import WahooCoordinator, WahooPowerZonesCoordinator
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

_PACKAGED_MAP_HTML = Path(__file__).parent / "web" / "map.html"
_VIEWER_VERSION_RE = re.compile(r"HAWahooligan-Viewer-Version:\s*(\d+)")

# Setup-phase timeout for each coordinator's first refresh. The Wahoo API
# client's 429 path can ``asyncio.sleep`` for up to ``Retry-After`` (default
# 300 s) before retrying — on a rate-limited Sandbox account that would
# block HA setup for up to 10 minutes (workout + power-zones coordinators
# in series). 30 s gives a healthy API plenty of room to respond and the
# user a snappy restart; the next regular poll picks up where setup left
# off if the API stays slow.
_FIRST_REFRESH_TIMEOUT_SECONDS = 30


@dataclass(slots=True)
class HawahooliganData:
    """Runtime data attached to the config entry."""

    api: WahooApi
    coordinator: WahooCoordinator
    power_zones_coordinator: WahooPowerZonesCoordinator


type HawahooliganConfigEntry = ConfigEntry[HawahooliganData]


def _require_current_scopes(entry: HawahooliganConfigEntry) -> None:
    """Trigger reauth at setup when the stored token lacks any scope SCOPES now requires.

    Skipped when the token has no ``scope`` field at all — older flows that didn't
    echo it would otherwise re-trigger reauth on every healthy restart.
    """
    granted_raw = (entry.data.get("token") or {}).get("scope")
    if not granted_raw:
        return
    missing = set(SCOPES.split()) - set(granted_raw.split())
    if missing:
        raise ConfigEntryAuthFailed(
            f"Wahoo OAuth token missing scopes: {sorted(missing)}. Click reauth."
        )


async def async_setup_entry(hass: HomeAssistant, entry: HawahooliganConfigEntry) -> bool:
    """Set up HAWahooligan from a config entry."""
    _require_current_scopes(entry)
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
        hass, entry
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    api = WahooApi(hass, session)
    coordinator = WahooCoordinator(hass, entry, api)
    power_zones_coordinator = WahooPowerZonesCoordinator(hass, entry, api)

    await hass.async_add_executor_job(_provision_viewer, Path(hass.config.path(*WWW_SUBPATH)))

    await coordinator.async_load_totals()
    await coordinator.async_load_workouts_index()
    await coordinator.async_load_details_cache()
    # If the user had a workout pinned before restart AND its detail
    # lives in the cache, seed ``coordinator.data`` so the per-workout
    # sensors come up populated even if the API stays rate-limited
    # through the first refresh.
    initial = coordinator.initial_data_from_cache()
    if initial is not None:
        coordinator.async_set_updated_data(initial)
    # Workout coordinator first refresh: cap the wait so a rate-limited
    # Wahoo response doesn't sleep up to 5 minutes inside ``_request``'s
    # ``Retry-After`` honour. Locally cached state (lifetime totals,
    # picker manifest, per-workout detail cache) is already loaded above,
    # so timing out here just means the per-workout sensors keep showing
    # the cached values until the next 15-min poll instead of blocking
    # HA setup.
    try:
        async with asyncio.timeout(_FIRST_REFRESH_TIMEOUT_SECONDS):
            await coordinator.async_config_entry_first_refresh()
    except TimeoutError:
        _LOGGER.warning(
            "Initial workout refresh timed out after %ds — Wahoo API is "
            "likely rate-limited. Continuing setup; the next regular poll "
            "will retry.",
            _FIRST_REFRESH_TIMEOUT_SECONDS,
        )
    except ConfigEntryNotReady:
        # ``async_config_entry_first_refresh`` translates ``UpdateFailed``
        # into ``ConfigEntryNotReady`` to trigger HA's setup-retry loop.
        # When the persistent detail cache already gave us data above,
        # though, we ARE ready — the failed poll just means we'll keep
        # showing the cached values until the next 15-min cycle. Re-raise
        # only when we have nothing at all.
        if coordinator.data is None:
            raise
        _LOGGER.info(
            "First refresh failed but the detail cache covers the pinned "
            "selection — continuing setup with cached values."
        )

    # The zones coordinator is allowed to fail without blocking setup —
    # a missing ``power_zones_read`` scope surfaces as a HA reauth
    # notification without taking the workout pipeline down with it. The
    # auth-failed branch has to start reauth manually because we catch it
    # here instead of letting it propagate to HA's setup machinery.
    try:
        async with asyncio.timeout(_FIRST_REFRESH_TIMEOUT_SECONDS):
            await power_zones_coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed as err:
        _LOGGER.info("Power-zones scope missing — starting reauth flow: %s", err)
        entry.async_start_reauth(hass)
    except TimeoutError:
        _LOGGER.warning(
            "Initial power-zones refresh timed out after %ds — continuing "
            "setup; the next 24h cycle will retry.",
            _FIRST_REFRESH_TIMEOUT_SECONDS,
        )
    except Exception as err:  # noqa: BLE001 — non-auth failures stay advisory
        _LOGGER.warning("Power-zones first refresh failed: %s", err)

    entry.runtime_data = HawahooliganData(
        api=api,
        coordinator=coordinator,
        power_zones_coordinator=power_zones_coordinator,
    )

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
