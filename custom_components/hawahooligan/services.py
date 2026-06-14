"""HA service handlers — render_workout, select_workout, full_backfill,
cleanup_geojson, refresh_power_zones.

See ``services.yaml`` + the README services table for per-service params and
when to use each."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import (
    CLEANUP_DEFAULT_MAX_AGE_DAYS,
    DOMAIN,
    FULL_BACKFILL_DEFAULT_BUDGET,
    FULL_BACKFILL_DEFAULT_WINDOW_SECONDS,
    FULL_BACKFILL_MAX_PAGES,
    SERVICE_CLEANUP_GEOJSON,
    SERVICE_FULL_BACKFILL,
    SERVICE_REFRESH_POWER_ZONES,
    SERVICE_RENDER_WORKOUT,
    SERVICE_SELECT_WORKOUT,
    SERVICE_SET_POWER_ZONES,
)
from .zones import default_zones_for

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
_ATTR_MAX_AGE_DAYS = "max_age_days"
_ATTR_FTP = "ftp"
_ATTR_CRITICAL_POWER = "critical_power"
_ATTR_WORKOUT_TYPE_ID = "workout_type_id"
_ZONE_KEYS: tuple[str, ...] = tuple(f"zone_{i}" for i in range(1, 8))

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

_CLEANUP_SCHEMA = vol.Schema(
    {
        vol.Optional(_ATTR_MAX_AGE_DAYS, default=CLEANUP_DEFAULT_MAX_AGE_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=3650)
        ),
        vol.Optional(_ATTR_CONFIG_ENTRY_ID): str,
    }
)

_REFRESH_POWER_ZONES_SCHEMA = vol.Schema(
    {
        vol.Optional(_ATTR_CONFIG_ENTRY_ID): str,
    }
)


_SET_POWER_ZONES_SCHEMA = vol.Schema(
    {
        vol.Required(_ATTR_FTP): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=1000.0)),
        vol.Optional(_ATTR_CRITICAL_POWER): vol.All(
            vol.Coerce(float), vol.Range(min=1.0, max=1000.0)
        ),
        vol.Optional(_ATTR_WORKOUT_TYPE_ID, default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=255)
        ),
        # Optional explicit zone boundaries; any absent fields are
        # derived from FTP via the Coggan defaults at service-call time.
        **{
            vol.Optional(zone): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2000.0))
            for zone in _ZONE_KEYS
        },
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
    if not hass.services.has_service(DOMAIN, SERVICE_CLEANUP_GEOJSON):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEANUP_GEOJSON,
            _handle_cleanup_geojson,
            schema=_CLEANUP_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_POWER_ZONES):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_POWER_ZONES,
            _handle_refresh_power_zones,
            schema=_REFRESH_POWER_ZONES_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_POWER_ZONES):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_POWER_ZONES,
            _handle_set_power_zones,
            schema=_SET_POWER_ZONES_SCHEMA,
        )


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove HAWahooligan services when the last entry unloads."""
    for service in (
        SERVICE_RENDER_WORKOUT,
        SERVICE_SELECT_WORKOUT,
        SERVICE_FULL_BACKFILL,
        SERVICE_CLEANUP_GEOJSON,
        SERVICE_REFRESH_POWER_ZONES,
        SERVICE_SET_POWER_ZONES,
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


async def _handle_cleanup_geojson(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call.hass, call.data.get(_ATTR_CONFIG_ENTRY_ID))
    max_age_days = int(call.data.get(_ATTR_MAX_AGE_DAYS, CLEANUP_DEFAULT_MAX_AGE_DAYS))
    try:
        removed = await coordinator.async_cleanup_geojson(max_age_days)
    except HomeAssistantError:
        raise
    except Exception as err:  # noqa: BLE001 — surface as HomeAssistantError
        raise HomeAssistantError(f"GeoJSON cleanup failed: {err}") from err
    _LOGGER.info(
        "cleanup_geojson: removed %d file(s) older than %d day(s)",
        removed,
        max_age_days,
    )


async def _handle_refresh_power_zones(call: ServiceCall) -> None:
    entry = _resolve_entry(call.hass, call.data.get(_ATTR_CONFIG_ENTRY_ID))
    coordinator = entry.runtime_data.power_zones_coordinator

    async def _run() -> None:
        try:
            await coordinator.async_refresh()
        except Exception as err:  # noqa: BLE001 — service must not crash HA
            _LOGGER.warning("refresh_power_zones aborted: %s", err)
            return
        if coordinator.last_update_success:
            _LOGGER.info(
                "refresh_power_zones: power zones updated (FTP / Critical Power "
                "sensors now reflect the latest Wahoo response)"
            )
        else:
            _LOGGER.warning(
                "refresh_power_zones: Wahoo refresh failed — sensors keep their "
                "previous values. Check the log for the underlying error."
            )

    # Fire-and-forget so a rate-limited Wahoo response doesn't make the
    # service-call dialog hang for up to 300 s on a Retry-After sleep.
    call.hass.async_create_background_task(_run(), name="hawahooligan_refresh_power_zones")
    _LOGGER.info(
        "refresh_power_zones: kicked off background refresh for entry %s",
        entry.entry_id,
    )


async def _handle_set_power_zones(call: ServiceCall) -> None:
    entry = _resolve_entry(call.hass, call.data.get(_ATTR_CONFIG_ENTRY_ID))
    api = entry.runtime_data.api
    coordinator = entry.runtime_data.power_zones_coordinator

    # Wahoo's API rejects float-shaped JSON for power values
    # (``"Invalid parameter 'zone_1' value 126.0: Must be a number"``).
    # Everything in the payload below is therefore cast to int at the
    # API boundary — power zones don't carry sub-watt precision anyway.
    ftp = int(round(float(call.data[_ATTR_FTP])))
    critical_power = int(round(float(call.data.get(_ATTR_CRITICAL_POWER, ftp))))
    workout_type_id = int(call.data.get(_ATTR_WORKOUT_TYPE_ID, 0))

    # Any zones the caller provided override the Wahoo-style defaults;
    # any they omit get filled from the derived table. Mixing is allowed
    # (e.g. user pins zone_4 to their exact LT, lets defaults handle the rest).
    derived = default_zones_for(ftp).as_dict()
    zones = {key: int(round(float(call.data.get(key, derived[key])))) for key in _ZONE_KEYS}

    payload: dict[str, object] = {
        "ftp": ftp,
        "critical_power": critical_power,
        "zone_count": 7,
        "workout_type_id": workout_type_id,
        **zones,
    }

    # GET first so we know whether to PUT (record exists for this
    # workout_type_id) or POST (none yet). Wahoo accepts duplicate
    # POSTs but treats each as a new record — we want one record per
    # workout_type_id, not a growing collection.
    try:
        existing = await api.async_get_power_zones()
    except Exception as err:  # noqa: BLE001 — surface as HomeAssistantError
        raise HomeAssistantError(f"set_power_zones: GET existing records failed: {err}") from err

    matching_id: int | None = None
    if isinstance(existing, list):
        for record in existing:
            if not isinstance(record, dict):
                continue
            if record.get("workout_type_id") == workout_type_id:
                rid = record.get("id")
                if isinstance(rid, int):
                    matching_id = rid
                    break

    try:
        if matching_id is None:
            await api.async_create_power_zones(payload)
            action = "POST"
        else:
            await api.async_update_power_zones(matching_id, payload)
            action = f"PUT id={matching_id}"
    except Exception as err:  # noqa: BLE001 — surface as HomeAssistantError
        raise HomeAssistantError(f"set_power_zones: write failed ({err})") from err

    # Refresh so the FTP / Critical Power sensors update immediately —
    # without this, the next change would only show up at the next daily poll.
    await coordinator.async_refresh()
    _LOGGER.info(
        "set_power_zones: %s for workout_type_id=%d (FTP=%g W, zones=%s)",
        action,
        workout_type_id,
        ftp,
        [int(zones[k]) for k in _ZONE_KEYS],
    )


def _resolve_entry(hass: HomeAssistant, entry_id: str | None) -> HawahooliganConfigEntry:
    """Locate a loaded HAWahooligan config entry — the shared resolver.

    With a single configured account (the common case) callers can omit
    ``config_entry_id``; with multiple accounts we require the caller to be
    explicit so we don't act on the wrong account.
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
        return entries[0]

    matching = [e for e in entries if e.entry_id == entry_id]
    if not matching:
        raise ServiceValidationError(f"No loaded HAWahooligan config entry with id {entry_id!r}")
    return matching[0]


def _resolve_coordinator(hass: HomeAssistant, entry_id: str | None):
    """Thin wrapper kept for the workout-coordinator callers."""
    return _resolve_entry(hass, entry_id).runtime_data.coordinator
