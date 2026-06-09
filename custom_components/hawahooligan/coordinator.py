"""DataUpdateCoordinator for the user's currently-selected Wahoo workout.

Per poll the coordinator issues one ``GET /v1/workouts?per_page=RECENT_COUNT``
listing call. By default the newest workout drives the headline sensors; if
the user explicitly picked a historic workout (via the
``hawahooligan.select_workout`` service / the bundled viewer dropdown) the
coordinator follows that selection instead — sensor state and map URL both
reflect the same chosen ride. The detail call (``GET /v1/workouts/:id``)
runs at most once per poll and is skipped when the target id is already in
the in-memory detail cache.

Picker UIs read ``<config>/www/hawahooligan/workouts.json`` (the manifest),
which now records the current ``selected_id`` so a fresh viewer load can
restore the right dropdown option.
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
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WahooApi, WahooApiError
from .const import (
    BACKFILL_COUNT,
    DOMAIN,
    EVENT_BACKFILL_PROGRESS,
    FULL_BACKFILL_DEFAULT_BUDGET,
    FULL_BACKFILL_DEFAULT_WINDOW_SECONDS,
    FULL_BACKFILL_MAX_PAGES,
    FULL_BACKFILL_PER_PAGE,
    MANIFEST_FILENAME,
    POWER_ZONES_UPDATE_INTERVAL,
    RECENT_COUNT,
    UPDATE_INTERVAL,
    WWW_SUBPATH,
    WWW_URL_PREFIX,
    is_indoor,
    workout_type_name,
)
from .fit import parse_fit_to_geojson, write_geojson
from .power_zones import PowerZonesData, parse_power_zones
from .rate_limit import RateLimitBudget
from .totals import SCHEMA_VERSION as _TOTALS_SCHEMA_VERSION
from .totals import LifetimeTotals, WorkoutContribution

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

    Reflects whichever workout the user is currently viewing (latest by
    default, or whatever they picked via :meth:`async_select_workout`).
    Numeric values are pre-cast to ``float`` and converted to the units the
    sensors advertise (km, km/h, min, …). Anything Wahoo doesn't supply for
    a given workout type stays as ``None`` so sensors can show ``unknown``.
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
    # Workout-level metadata exposed only as attributes on the headline
    # sensor — useful for automations ("trigger when ride uses Route X")
    # and for the Phase-5 routes/plans bridge. Wahoo omits these on
    # workouts with no plan / no route, so all three default to ``None``.
    route_id: int | None = None
    plan_id: int | None = None
    plan_ids: list[int] = field(default_factory=list)
    # Summary fields (units already applied)
    distance_km: float | None = None
    ascent_m: float | None = None
    duration_min: float | None = None
    duration_total_min: float | None = None
    duration_paused_min: float | None = None
    speed_avg_kmh: float | None = None
    power_avg_w: float | None = None
    power_np_w: float | None = None
    tss: float | None = None
    heart_rate_avg_bpm: float | None = None
    cadence_avg_rpm: float | None = None
    calories_kcal: float | None = None
    work_kj: float | None = None
    # Picker context
    recent: list[RecentWorkout] = field(default_factory=list)
    selected_workout_id: int | None = None


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
    duration_total_s = _as_float(summary.get("duration_total_accum"))
    duration_paused_s = _as_float(summary.get("duration_paused_accum"))
    speed_ms = _as_float(summary.get("speed_avg"))
    work_j = _as_float(summary.get("work_accum"))

    plan_ids_raw = workout.get("plan_ids") or []
    plan_ids: list[int] = []
    if isinstance(plan_ids_raw, list):
        for pid in plan_ids_raw:
            try:
                plan_ids.append(int(pid))
            except (TypeError, ValueError):
                continue

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
        route_id=workout.get("route_id"),
        plan_id=workout.get("plan_id"),
        plan_ids=plan_ids,
        distance_km=distance_m / 1000.0 if distance_m is not None else None,
        ascent_m=_as_float(summary.get("ascent_accum")),
        duration_min=duration_s / 60.0 if duration_s is not None else None,
        duration_total_min=(duration_total_s / 60.0 if duration_total_s is not None else None),
        duration_paused_min=(duration_paused_s / 60.0 if duration_paused_s is not None else None),
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


def _write_manifest(directory: Path, recent: list[RecentWorkout], selected_id: int | None) -> None:
    """Blocking: rewrite the picker manifest from a fresh ``recent`` list.

    Re-derives ``has_track`` from the filesystem so the manifest always agrees
    with what's actually on disk, even if a workout's track gets cleared
    between polls. ``selected_id`` is exported so a freshly-loaded viewer can
    pre-select the right option without round-tripping HA.
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
    payload = json.dumps(
        {"workouts": entries, "selected_id": selected_id},
        separators=(",", ":"),
    )
    (directory / MANIFEST_FILENAME).write_text(payload, encoding="utf-8")


class WahooCoordinator(DataUpdateCoordinator[WorkoutData | None]):
    """Polls Wahoo Cloud and serves the currently-selected workout."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: WahooApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({entry.title})",
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self._api = api
        self._entry_id = entry.entry_id
        # ``None`` means "follow latest"; an int pins to a specific workout id.
        self._selected_workout_id: int | None = None
        # Track the workout we last fully fetched so we can skip the extra
        # detail call when nothing changed since the previous poll.
        self._last_target_id: int | None = None
        self._last_latest_summary_was_null: bool = True
        # WorkoutData by workout_id — historic picks are reused from here so
        # toggling between rides doesn't burn a Wahoo API call each time.
        self._detail_cache: dict[int, WorkoutData] = {}
        # Lifetime totals are persisted per-entry so they survive HA restarts
        # without re-counting workouts. The store is keyed off the entry id
        # to keep multi-account installs isolated.
        self._totals: LifetimeTotals = LifetimeTotals()
        self._totals_store: Store = Store(
            hass,
            _TOTALS_SCHEMA_VERSION,
            f"{DOMAIN}_totals_{entry.entry_id}",
        )

    @property
    def _geojson_dir(self) -> Path:
        return Path(self.hass.config.path(*WWW_SUBPATH))

    @property
    def selected_workout_id(self) -> int | None:
        """Currently pinned workout id, or ``None`` when following latest."""
        return self._selected_workout_id

    @property
    def totals(self) -> LifetimeTotals:
        """Lifetime totals accumulator. Survives HA restarts via the store."""
        return self._totals

    async def async_load_totals(self) -> None:
        """Rehydrate lifetime totals from the persistent store at setup time."""
        try:
            payload = await self._totals_store.async_load()
        except Exception as err:  # noqa: BLE001 — load failure must not block setup
            _LOGGER.warning("Could not load lifetime totals: %s", err)
            return
        self._totals = LifetimeTotals.from_storage(payload)
        if self._totals.workout_count:
            _LOGGER.debug(
                "Loaded lifetime totals: %d workouts, %.1f km",
                self._totals.workout_count,
                self._totals.distance_km,
            )

    async def _record_totals(self, data: WorkoutData) -> bool:
        """Feed ``data`` into the lifetime totals if its id hasn't been seen.

        Returns ``True`` when the workout was a fresh contribution. Persists
        the updated state asynchronously so a crash before the next save
        loses at most one workout's worth of accumulation.
        """
        if data.workout_id is None:
            return False
        added = self._totals.add(
            WorkoutContribution(
                workout_id=data.workout_id,
                indoor=data.indoor,
                distance_km=data.distance_km,
                ascent_m=data.ascent_m,
                duration_min=data.duration_min,
                calories_kcal=data.calories_kcal,
                work_kj=data.work_kj,
                tss=data.tss,
            )
        )
        if added:
            try:
                await self._totals_store.async_save(self._totals.as_storage())
            except Exception as err:  # noqa: BLE001 — save failure must not break poll
                _LOGGER.warning("Could not persist lifetime totals: %s", err)
        return added

    async def async_select_workout(self, workout_id: int | None) -> None:
        """Pin the sensors and map to ``workout_id`` (or ``None`` for latest).

        Invalidates the detail cache for the previously-selected workout so a
        re-pick after a re-render picks up the new file URL. Triggers an
        immediate refresh so the viewer sees the change without waiting up to
        15 minutes for the next poll.
        """
        if workout_id == self._selected_workout_id:
            return
        self._selected_workout_id = workout_id
        await self.async_request_refresh()

    async def _async_update_data(self) -> WorkoutData | None:
        try:
            listing = await self._api.async_get_workouts(per_page=RECENT_COUNT)
        except WahooApiError as err:
            raise UpdateFailed(str(err)) from err

        workouts = listing.get("workouts") or []
        if not workouts:
            self._last_target_id = None
            self._last_latest_summary_was_null = True
            await self._refresh_manifest([], None)
            return None

        latest = workouts[0]
        latest_id = latest.get("id")
        listing_summary = latest.get("workout_summary")

        recent = await self.hass.async_add_executor_job(
            _build_recent_from_listing, workouts, self._geojson_dir
        )

        target_id = self._resolve_target_id(latest_id)

        # Decide whether the detail call is necessary. For "follow latest"
        # we re-use the existing change-detection (summary may settle late);
        # for historic picks we lean on the in-memory cache.
        if target_id == latest_id:
            needs_detail = (
                target_id != self._last_target_id
                or self.data is None
                or self.data.workout_id != target_id
                or self._last_latest_summary_was_null
            )
        else:
            needs_detail = target_id not in self._detail_cache

        if needs_detail:
            try:
                detail = await self._api.async_get_workout(target_id)
            except WahooApiError as err:
                # When a historic pick fails, fall back to whatever we have so
                # the headline sensors stay coherent. Latest failures still
                # need to surface as UpdateFailed.
                if target_id == latest_id:
                    raise UpdateFailed(str(err)) from err
                _LOGGER.warning(
                    "Could not fetch selected workout %s: %s — falling back to latest",
                    target_id,
                    err,
                )
                self._selected_workout_id = None
                target_id = latest_id
                try:
                    detail = await self._api.async_get_workout(target_id)
                except WahooApiError as inner_err:
                    raise UpdateFailed(str(inner_err)) from inner_err

            data = _build_workout_data(detail)
            data.recent = recent
            data.selected_workout_id = self._selected_workout_id
            await self._record_totals(data)

            # Render the track on first sight or when the previously rendered
            # file disappeared (user cleared www/). Indoor/manual rides skip
            # silently — they don't have GPS to render.
            if (
                data.workout_id is not None
                and data.file_url
                and not data.manual
                and not data.indoor
            ):
                already_rendered = await self.hass.async_add_executor_job(
                    _has_geojson, self._geojson_dir, data.workout_id
                )
                if not already_rendered:
                    data.geojson_url = await self._render(data.workout_id, data.file_url)
                else:
                    data.geojson_url = f"{WWW_URL_PREFIX}/{data.workout_id}.geojson"

            self._detail_cache[target_id] = data
            if target_id == latest_id:
                self._last_latest_summary_was_null = (
                    detail.get("workout_summary") in (None, {}) and listing_summary is None
                )
            self._last_target_id = target_id
            await self._refresh_manifest(recent, self._selected_workout_id)
            return data

        # No new detail call required. Reuse the cached WorkoutData but make
        # sure the cheap context fields (recent list, current selection) keep
        # ticking with each poll.
        data = self._detail_cache.get(target_id) or self.data
        if data is None:
            # Shouldn't happen: a target_id with no fetch and no cache means a
            # logic regression. Detail-fetch defensively rather than crash.
            try:
                detail = await self._api.async_get_workout(target_id)
            except WahooApiError as err:
                raise UpdateFailed(str(err)) from err
            data = _build_workout_data(detail)
            self._detail_cache[target_id] = data

        data.recent = recent
        data.selected_workout_id = self._selected_workout_id
        self._last_target_id = target_id
        await self._refresh_manifest(recent, self._selected_workout_id)
        return data

    def _resolve_target_id(self, latest_id: int) -> int:
        """Resolve the selection to a concrete workout id for this poll."""
        if self._selected_workout_id is None:
            return latest_id
        return self._selected_workout_id

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

    async def _refresh_manifest(self, recent: list[RecentWorkout], selected_id: int | None) -> None:
        """Rewrite the picker manifest in the executor; never raises."""
        try:
            await self.hass.async_add_executor_job(
                _write_manifest, self._geojson_dir, recent, selected_id
            )
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
        await self._record_totals(data)
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
        """Render + record-totals over the last ``count`` workouts.

        Returns the number of newly rendered tracks. The detail call (the only
        rate-limited part) runs at most once per workout that's still missing
        from the lifetime totals OR from disk — already-rendered + already-
        accumulated workouts cost zero API quota on subsequent restarts. Auth
        failures bubble up so HA can reauth.

        Also refreshes the picker manifest with whatever the listing returned
        so the viewer sees the historic rides even before the next poll runs.

        Wraps detail calls in the same sandbox-safe rate-limit budget the
        full-history backfill uses so the initial 20-call burst can't trip
        the Wahoo Sandbox 25 / 5-min ceiling.
        """
        budget = RateLimitBudget(FULL_BACKFILL_DEFAULT_BUDGET, FULL_BACKFILL_DEFAULT_WINDOW_SECONDS)
        await budget.acquire()
        try:
            listing = await self._api.async_get_workouts(per_page=count)
        except WahooApiError as err:
            _LOGGER.warning("Backfill listing call failed: %s", err)
            return 0

        workouts = listing.get("workouts") or []

        rendered = 0
        # Pulling the same 429 back-to-back means Wahoo's larger window (the
        # hourly or daily cap, not the rolling 5-min one) is exhausted. Keep
        # trying just floods the log without making progress, so bail out
        # after a handful and leave the next poll to retry the listing call.
        consecutive_429s = 0
        max_consecutive_429s = 3
        for workout in workouts:
            workout_id = workout.get("id")
            if workout_id is None:
                continue

            geojson_exists = await self.hass.async_add_executor_job(
                _has_geojson, self._geojson_dir, workout_id
            )
            totals_recorded = workout_id in self._totals.workouts
            if geojson_exists and totals_recorded:
                continue

            await budget.acquire()
            try:
                detail = await self._api.async_get_workout(workout_id)
            except WahooApiError as err:
                _LOGGER.warning("Backfill detail fetch for %s failed: %s", workout_id, err)
                if err.status_code == 429:
                    consecutive_429s += 1
                    if consecutive_429s >= max_consecutive_429s:
                        _LOGGER.warning(
                            "Backfill aborting after %d consecutive 429s — Wahoo's "
                            "larger rate-limit window is exhausted; the next regular "
                            "poll will resume work once the quota recovers (Sandbox "
                            "tier resets daily at 00:00 UTC)",
                            consecutive_429s,
                        )
                        break
                continue
            consecutive_429s = 0

            data = _build_workout_data(detail)
            if not totals_recorded:
                await self._record_totals(data)

            if not geojson_exists and data.file_url and not data.manual and not data.indoor:
                url = await self._render(data.workout_id, data.file_url)
                if url is not None:
                    rendered += 1

        recent = await self.hass.async_add_executor_job(
            _build_recent_from_listing, workouts, self._geojson_dir
        )
        await self._refresh_manifest(recent, self._selected_workout_id)
        return rendered

    async def async_full_backfill(
        self,
        *,
        with_tracks: bool = False,
        max_pages: int = FULL_BACKFILL_MAX_PAGES,
        max_calls_per_window: int = FULL_BACKFILL_DEFAULT_BUDGET,
        window_seconds: float = FULL_BACKFILL_DEFAULT_WINDOW_SECONDS,
    ) -> int:
        """Walk the user's whole Wahoo history into lifetime totals.

        Iterates ``GET /v1/workouts?page=N&per_page=FULL_BACKFILL_PER_PAGE``
        until the API returns an empty list (or ``max_pages`` is reached).
        For each workout not yet in the totals (and not yet on disk when
        ``with_tracks=True``), fetches detail and records it.

        Rate-limit budget defaults sit just under the Sandbox 25 / 5-min
        ceiling — pass higher numbers if your Wahoo app is on the
        production tier. Auth failures (rotating refresh token, missing
        scope) bubble up as ``ConfigEntryAuthFailed``; other errors abort
        the loop and return the count accumulated so far.

        Fires :data:`hawahooligan.const.EVENT_BACKFILL_PROGRESS` after each
        page so users can wire a notification automation.
        """
        budget = RateLimitBudget(max_calls_per_window, window_seconds)
        added_total = 0
        processed_total = 0

        try:
            for page in range(1, max_pages + 1):
                # Listing call also counts against the budget.
                await budget.acquire()
                try:
                    listing = await self._api.async_get_workouts(
                        per_page=FULL_BACKFILL_PER_PAGE, page=page
                    )
                except WahooApiError as err:
                    _LOGGER.warning(
                        "Full backfill listing call failed on page %d: %s",
                        page,
                        err,
                    )
                    break

                workouts = listing.get("workouts") or []
                if not workouts:
                    self._emit_backfill_event(
                        page=page,
                        processed=processed_total,
                        added=added_total,
                        done=True,
                    )
                    _LOGGER.info(
                        "Full backfill complete after %d page(s): %d workouts added (%d seen)",
                        page,
                        added_total,
                        processed_total,
                    )
                    return added_total

                page_added = 0
                for workout in workouts:
                    workout_id = workout.get("id")
                    if workout_id is None:
                        continue
                    processed_total += 1

                    needs_detail = workout_id not in self._totals.workouts
                    if with_tracks and not needs_detail:
                        needs_detail = not await self.hass.async_add_executor_job(
                            _has_geojson, self._geojson_dir, workout_id
                        )
                    if not needs_detail:
                        continue

                    await budget.acquire()
                    try:
                        detail = await self._api.async_get_workout(workout_id)
                    except WahooApiError as err:
                        _LOGGER.warning(
                            "Full backfill detail fetch for %s failed: %s",
                            workout_id,
                            err,
                        )
                        continue

                    data = _build_workout_data(detail)
                    if workout_id not in self._totals.workouts and await self._record_totals(data):
                        added_total += 1
                        page_added += 1

                    if with_tracks and data.file_url and not data.manual and not data.indoor:
                        await self._render(data.workout_id, data.file_url)

                self._emit_backfill_event(
                    page=page,
                    processed=processed_total,
                    added=added_total,
                    done=False,
                )
                _LOGGER.info(
                    "Full backfill page %d: %d processed, %d new (total %d)",
                    page,
                    len(workouts),
                    page_added,
                    added_total,
                )

            _LOGGER.warning(
                "Full backfill hit the %d-page safety guard before reaching an empty page",
                max_pages,
            )
            self._emit_backfill_event(
                page=max_pages,
                processed=processed_total,
                added=added_total,
                done=True,
            )
        except ConfigEntryAuthFailed:
            self._emit_backfill_event(
                page=0,
                processed=processed_total,
                added=added_total,
                done=True,
            )
            raise

        return added_total

    def _emit_backfill_event(self, *, page: int, processed: int, added: int, done: bool) -> None:
        self.hass.bus.async_fire(
            EVENT_BACKFILL_PROGRESS,
            {
                "entry_id": self._entry_id,
                "page": page,
                "processed": processed,
                "added": added,
                "done": done,
            },
        )


class WahooPowerZonesCoordinator(DataUpdateCoordinator[PowerZonesData | None]):
    """Polls ``GET /v1/power_zones`` once a day.

    Failures here are isolated from the main workout pipeline — the workout
    coordinator runs on its own update interval and doesn't share state.
    An auth/scope problem (HTTP 401/403) still bubbles up as
    ``ConfigEntryAuthFailed`` so HA can drive the reauth flow.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: WahooApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} power zones ({entry.title})",
            update_interval=POWER_ZONES_UPDATE_INTERVAL,
            config_entry=entry,
        )
        self._api = api

    async def _async_update_data(self) -> PowerZonesData | None:
        try:
            response = await self._api.async_get_power_zones()
        except WahooApiError as err:
            raise UpdateFailed(str(err)) from err
        return parse_power_zones(response)
