"""DataUpdateCoordinator for the most recent Wahoo workout.

Per poll the coordinator issues one ``GET /v1/workouts?per_page=RECENT_COUNT``
listing call. The newest workout drives the headline sensors; the rest stays
visible as a lightweight ``recent`` list on the same sensor's attributes and
in the picker manifest the viewer reads. Only the **newest** workout is ever
detail-fetched, and only when its id changed (or the previous summary was
still ``None``) — so the typical poll spends 1 API call against the Wahoo
rate limit and 0 detail calls.

When a new outdoor workout appears the coordinator pulls its FIT, converts
to GeoJSON and drops the file under ``<config>/www/hawahooligan/`` next to
``workouts.json`` (the picker manifest). The same render path is exposed
via :meth:`async_render_workout` for the backfill loop and the
``hawahooligan.render_workout`` service.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WahooApi, WahooApiError
from .const import (
    BACKFILL_COUNT,
    DOMAIN,
    MANIFEST_FILENAME,
    RECENT_COUNT,
    UPDATE_INTERVAL,
    WWW_SUBPATH,
    WWW_URL_PREFIX,
    is_indoor,
    workout_type_name,
)
from .fit import parse_fit_to_geojson, write_geojson

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RecentWorkout:
    """Lean summary of one entry in the rolling recent-workouts window.

    Picker UIs only need enough to render a "27 Apr — Morning ride" option and
    look up the GeoJSON on disk; the full :class:`WorkoutData` is overkill
    here. ``has_track`` records whether the corresponding ``<id>.geojson`` has
    actually been rendered — indoor and manual entries stay listed for context
    but mark this ``False`` so the viewer can disable them.
    """

    id: int
    name: str | None
    starts: str | None
    workout_type_id: int | None
    workout_type_name: str | None
    indoor: bool
    manual: bool
    has_track: bool


@dataclass(slots=True)
class WorkoutData:
    """Shape exposed to sensor entities.

    Numeric values are pre-cast to ``float`` and converted to the units the
    sensors advertise (km, km/h, min, …). Anything Wahoo doesn't supply for a
    given workout type stays as ``None`` so sensors can show ``unknown``.
    """

    workout_id: int | None = None
    name: str | None = None
    starts: str | None = None
    workout_type_id: int | None = None
    workout_type_name: str | None = None
    indoor: bool = False
    manual: bool = False
    edited: bool = False
    time_zone: str | None = None
    fitness_app_id: int | None = None
    file_url: str | None = None
    geojson_url: str | None = None
    # Summary fields (units already applied)
    distance_km: float | None = None
    ascent_m: float | None = None
    duration_min: float | None = None
    speed_avg_kmh: float | None = None
    power_avg_w: float | None = None
    power_np_w: float | None = None
    tss: float | None = None
    heart_rate_avg_bpm: float | None = None
    cadence_avg_rpm: float | None = None
    calories_kcal: float | None = None
    work_kj: float | None = None
    recent: list[RecentWorkout] = field(default_factory=list)


def _as_float(value: Any) -> float | None:
    """Parse a Wahoo summary string into a float (returns ``None`` on failure).

    Summary values come back as strings ("1234.56"); ``None`` and empty strings
    are both treated as "absent" because Wahoo omits fields per workout type.
    """
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_workout_data(workout: dict[str, Any]) -> WorkoutData:
    """Map a Wahoo ``GET /v1/workouts/:id`` response onto :class:`WorkoutData`."""
    summary = workout.get("workout_summary") or {}
    file_obj = summary.get("file") or {}
    type_id = workout.get("workout_type_id")

    distance_m = _as_float(summary.get("distance_accum"))
    duration_s = _as_float(summary.get("duration_active_accum"))
    speed_ms = _as_float(summary.get("speed_avg"))
    work_j = _as_float(summary.get("work_accum"))

    return WorkoutData(
        workout_id=workout.get("id"),
        name=workout.get("name") or summary.get("name"),
        starts=workout.get("starts"),
        workout_type_id=type_id,
        workout_type_name=workout_type_name(type_id),
        indoor=is_indoor(type_id),
        manual=bool(workout.get("manual") or summary.get("manual")),
        edited=bool(workout.get("edited") or summary.get("edited")),
        time_zone=workout.get("time_zone") or summary.get("time_zone"),
        fitness_app_id=workout.get("fitness_app_id"),
        file_url=file_obj.get("url"),
        distance_km=distance_m / 1000.0 if distance_m is not None else None,
        ascent_m=_as_float(summary.get("ascent_accum")),
        duration_min=duration_s / 60.0 if duration_s is not None else None,
        speed_avg_kmh=speed_ms * 3.6 if speed_ms is not None else None,
        power_avg_w=_as_float(summary.get("power_avg")),
        power_np_w=_as_float(summary.get("power_bike_np_last")),
        tss=_as_float(summary.get("power_bike_tss_last")),
        heart_rate_avg_bpm=_as_float(summary.get("heart_rate_avg")),
        cadence_avg_rpm=_as_float(summary.get("cadence_avg")),
        calories_kcal=_as_float(summary.get("calories_accum")),
        work_kj=work_j / 1000.0 if work_j is not None else None,
    )


def _build_recent_from_listing(
    workouts: list[dict[str, Any]],
    directory: Path,
) -> list[RecentWorkout]:
    """Map raw listing entries onto :class:`RecentWorkout`, sorted desc by ``starts``.

    Skips entries without an id (defensive against API shape drift). The
    ``has_track`` flag is filled from the filesystem — the viewer uses it to
    distinguish renderable rides from indoor/manual sessions.
    """
    result: list[RecentWorkout] = []
    for workout in workouts:
        workout_id = workout.get("id")
        if workout_id is None:
            continue
        type_id = workout.get("workout_type_id")
        summary = workout.get("workout_summary") or {}
        result.append(
            RecentWorkout(
                id=workout_id,
                name=workout.get("name") or summary.get("name"),
                starts=workout.get("starts"),
                workout_type_id=type_id,
                workout_type_name=workout_type_name(type_id),
                indoor=is_indoor(type_id),
                manual=bool(workout.get("manual") or summary.get("manual")),
                has_track=(directory / f"{workout_id}.geojson").is_file(),
            )
        )
    # Listing comes back desc by ``starts`` already, but lean on a Python sort
    # so a malformed response doesn't reorder the picker silently.
    result.sort(key=lambda r: r.starts or "", reverse=True)
    return result


def _parse_and_write_fit(directory: Path, workout_id: int | str, payload: bytes) -> str | None:
    """Blocking helper: decode FIT, write GeoJSON, return public URL or ``None``.

    Lives at module scope so the executor can run it without dragging the
    coordinator instance along.
    """
    feature = parse_fit_to_geojson(payload)
    if feature is None:
        return None
    write_geojson(directory, workout_id, feature)
    return f"{WWW_URL_PREFIX}/{workout_id}.geojson"


def _geojson_path(directory: Path, workout_id: int | str) -> Path:
    return directory / f"{workout_id}.geojson"


def _has_geojson(directory: Path, workout_id: int | str) -> bool:
    """Blocking filesystem check — caller dispatches via executor."""
    return _geojson_path(directory, workout_id).is_file()


def _write_manifest(directory: Path, recent: list[RecentWorkout]) -> None:
    """Blocking: rewrite the picker manifest from a fresh ``recent`` list.

    Re-derives ``has_track`` from the filesystem so the manifest always agrees
    with what's actually on disk, even if a workout's track gets cleared
    between polls.
    """
    directory.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for r in recent:
        entries.append(
            {
                "id": r.id,
                "name": r.name,
                "starts": r.starts,
                "workout_type_id": r.workout_type_id,
                "workout_type": r.workout_type_name,
                "indoor": r.indoor,
                "manual": r.manual,
                "has_track": (directory / f"{r.id}.geojson").is_file(),
            }
        )
    payload = json.dumps({"workouts": entries}, separators=(",", ":"))
    (directory / MANIFEST_FILENAME).write_text(payload, encoding="utf-8")


class WahooCoordinator(DataUpdateCoordinator[WorkoutData | None]):
    """Polls Wahoo Cloud for the user's most recent workout."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: WahooApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({entry.title})",
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self._api = api
        # Track the workout we last fully fetched so we can skip the extra
        # detail call when nothing changed since the previous poll.
        self._last_id: int | None = None
        self._last_summary_was_null: bool = True

    @property
    def _geojson_dir(self) -> Path:
        return Path(self.hass.config.path(*WWW_SUBPATH))

    async def _async_update_data(self) -> WorkoutData | None:
        try:
            listing = await self._api.async_get_workouts(per_page=RECENT_COUNT)
        except WahooApiError as err:
            raise UpdateFailed(str(err)) from err

        workouts = listing.get("workouts") or []
        if not workouts:
            self._last_id = None
            self._last_summary_was_null = True
            await self._refresh_manifest([])
            return None

        latest = workouts[0]
        latest_id = latest.get("id")
        listing_summary = latest.get("workout_summary")

        recent = await self.hass.async_add_executor_job(
            _build_recent_from_listing, workouts, self._geojson_dir
        )

        # Only pull the full object when something genuinely changed. Frisch
        # beendete Fahrten kommen mit `workout_summary == None` zurück; in dem
        # Fall ebenfalls erneut nachladen, damit der nächste Poll die Werte
        # einsammeln kann, sobald Wahoo sie veröffentlicht hat.
        needs_detail = (
            latest_id != self._last_id or self.data is None or self._last_summary_was_null
        )
        if not needs_detail:
            # Returning the existing ``WorkoutData`` but refresh ``recent`` so
            # newly rendered tracks (backfill / service) show up in the picker.
            current = self.data
            if current is not None:
                current.recent = recent
            await self._refresh_manifest(recent)
            return current

        try:
            detail = await self._api.async_get_workout(latest_id)
        except WahooApiError as err:
            raise UpdateFailed(str(err)) from err

        data = _build_workout_data(detail)
        data.recent = recent

        # Render the track on first sight or when the previously rendered
        # file disappeared (user cleared www/). Indoor/manual rides skip
        # silently — they don't have GPS to render.
        if data.workout_id is not None and data.file_url and not data.manual and not data.indoor:
            already_rendered = await self.hass.async_add_executor_job(
                _has_geojson, self._geojson_dir, data.workout_id
            )
            if not already_rendered or latest_id != self._last_id:
                data.geojson_url = await self._render(data.workout_id, data.file_url)
            else:
                data.geojson_url = f"{WWW_URL_PREFIX}/{data.workout_id}.geojson"

        self._last_id = latest_id
        self._last_summary_was_null = (
            detail.get("workout_summary") in (None, {}) and listing_summary is None
        )
        await self._refresh_manifest(recent)
        return data

    async def _render(self, workout_id: int | str, file_url: str) -> str | None:
        """Download the FIT for ``workout_id`` and write the GeoJSON track.

        Errors here never break the update — at worst the headline sensors fill
        in and the map stays empty until the next workout shows up. Auth
        failures still propagate so HA can launch reauth.
        """
        try:
            payload = await self._api.async_download_fit(file_url)
        except ConfigEntryAuthFailed:
            raise
        if payload is None:
            return None
        try:
            return await self.hass.async_add_executor_job(
                _parse_and_write_fit, self._geojson_dir, workout_id, payload
            )
        except OSError as err:
            _LOGGER.warning("FIT GeoJSON write for workout %s failed: %s", workout_id, err)
            return None

    async def _refresh_manifest(self, recent: list[RecentWorkout]) -> None:
        """Rewrite the picker manifest in the executor; never raises."""
        try:
            await self.hass.async_add_executor_job(_write_manifest, self._geojson_dir, recent)
        except OSError as err:
            _LOGGER.warning("Could not refresh picker manifest: %s", err)

    async def async_render_workout(
        self, workout_id: int | str, *, force: bool = False
    ) -> str | None:
        """Render the GeoJSON for an arbitrary Wahoo workout id.

        Used both by the backfill loop (no-op when the file is already on
        disk) and the ``render_workout`` service (``force=True`` so users can
        re-render after a viewer/track bump).

        Returns the public ``/local/...`` URL when a track was produced,
        ``None`` when there's nothing to render (indoor, manual, no GPS).
        """
        if not force:
            exists = await self.hass.async_add_executor_job(
                _has_geojson, self._geojson_dir, workout_id
            )
            if exists:
                return f"{WWW_URL_PREFIX}/{workout_id}.geojson"

        try:
            detail = await self._api.async_get_workout(workout_id)
        except WahooApiError as err:
            _LOGGER.warning("Could not fetch workout %s for render: %s", workout_id, err)
            return None

        data = _build_workout_data(detail)
        if data.manual or data.indoor or not data.file_url:
            _LOGGER.debug(
                "Workout %s has no renderable track (indoor=%s manual=%s file_url=%s)",
                workout_id,
                data.indoor,
                data.manual,
                bool(data.file_url),
            )
            return None
        return await self._render(workout_id, data.file_url)

    async def async_backfill_recent(self, count: int = BACKFILL_COUNT) -> int:
        """Render up to ``count`` most-recent outdoor workouts that aren't on disk.

        Returns the number of newly rendered tracks. Listing call counts
        against the Wahoo rate limit; detail calls only happen for workouts
        whose GeoJSON is missing. Auth failures bubble up so HA can reauth.
        Also refreshes the picker manifest with whatever the listing returned
        so the viewer sees the historic rides even before the next poll runs.
        """
        try:
            listing = await self._api.async_get_workouts(per_page=count)
        except WahooApiError as err:
            _LOGGER.warning("Backfill listing call failed: %s", err)
            return 0

        workouts = listing.get("workouts") or []

        rendered = 0
        for workout in workouts:
            workout_id = workout.get("id")
            if workout_id is None:
                continue
            if await self.hass.async_add_executor_job(_has_geojson, self._geojson_dir, workout_id):
                continue
            url = await self.async_render_workout(workout_id)
            if url is not None:
                rendered += 1

        recent = await self.hass.async_add_executor_job(
            _build_recent_from_listing, workouts, self._geojson_dir
        )
        await self._refresh_manifest(recent)
        return rendered
