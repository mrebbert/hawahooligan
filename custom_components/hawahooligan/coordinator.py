"""DataUpdateCoordinator: one listing call + at most one detail call per poll.

Default target is the newest workout; a service / picker selection overrides
that. Detail responses are cached in memory (and persisted to disk) so
historic picks are free on subsequent polls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field, fields
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
    EVENT_PERSONAL_RECORD,
    FULL_BACKFILL_DEFAULT_BUDGET,
    FULL_BACKFILL_DEFAULT_WINDOW_SECONDS,
    FULL_BACKFILL_MAX_PAGES,
    FULL_BACKFILL_PER_PAGE,
    POWER_ZONES_UPDATE_INTERVAL,
    RECENT_COUNT,
    UPDATE_INTERVAL,
    WWW_SUBPATH,
    WWW_URL_PREFIX,
    is_indoor,
    workout_type_name,
)
from .fit import parse_fit_to_geojson, write_geojson
from .manifest import (
    RecentWorkout,
    merge_and_write_manifest,
    prune_manifest,
    read_manifest_entries,
    read_selected_workout_id,
)
from .power_zones import PowerZonesData, parse_power_zones
from .rate_limit import ConsecutiveLimitGuard, RateLimitBudget
from .records import detect_personal_records
from .totals import SCHEMA_VERSION as _TOTALS_SCHEMA_VERSION
from .totals import LifetimeTotals, WorkoutContribution

_LOGGER = logging.getLogger(__name__)

# Per-workout detail cache persists across restarts so historic picks
# don't burn an API call after every reboot. Schema bump when
# ``WorkoutData`` gains a required field that can't default sanely.
_DETAILS_SCHEMA_VERSION = 1

# Debounce writes to the details cache — backfill loops drop 20+
# entries in a few seconds; without the delay we'd hit disk 20 times
# back-to-back. 10 s is long enough to coalesce, short enough that an
# unclean shutdown loses at most one debounce window's worth.
_DETAILS_SAVE_DELAY_SECONDS = 10

# Picker-context fields don't belong in the per-workout cache — they're
# rebuilt from the manifest + selected_id every poll.
_DETAILS_TRANSIENT_FIELDS = frozenset({"recent", "selected_workout_id"})


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


def workout_data_to_storage(data: WorkoutData) -> dict[str, Any]:
    """Serialize ``WorkoutData`` for the per-workout detail cache.

    Strips transient picker context (``recent``, ``selected_workout_id``)
    so the cache stays workout-scoped — those fields are rebuilt from
    the manifest + the coordinator's selected_id on every poll.
    """
    out = asdict(data)
    for key in _DETAILS_TRANSIENT_FIELDS:
        out.pop(key, None)
    return out


def workout_data_from_storage(payload: dict[str, Any]) -> WorkoutData | None:
    """Rehydrate ``WorkoutData`` from the cache, tolerating field drift.

    Forward-compat: keys we don't recognize get filtered out so old
    cache files don't fail to load after a schema bump. Fields that
    were added since the cache was written use their dataclass
    defaults.
    """
    if not isinstance(payload, dict):
        return None
    known = {f.name for f in fields(WorkoutData)}
    filtered = {k: v for k, v in payload.items() if k in known}
    if not filtered:
        return None
    try:
        return WorkoutData(**filtered)
    except (TypeError, ValueError):
        return None


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
        duration_s = _as_float(summary.get("duration_active_accum"))
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
                duration_min=duration_s / 60.0 if duration_s is not None else None,
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


def _cleanup_geojson(directory: Path, cutoff_epoch: float) -> set[int]:
    """Blocking: delete per-workout ``<id>.geojson`` files older than ``cutoff_epoch``.

    Returns the set of removed workout ids — empty set if the dir is missing
    or nothing matched. Per-file failures are skipped so one stuck file
    doesn't block the rest. The companion ``latest.geojson`` (re-written on
    every poll) is intentionally excluded by the numeric-stem filter.
    """
    if not directory.is_dir():
        return set()
    removed: set[int] = set()
    for path in directory.glob("*.geojson"):
        try:
            workout_id = int(path.stem)
        except ValueError:
            # ``latest.geojson`` or any other non-numeric stem — leave it.
            continue
        try:
            if path.stat().st_mtime < cutoff_epoch:
                path.unlink()
                removed.add(workout_id)
        except OSError:
            # Permission errors / races with another writer — re-runnable.
            continue
    return removed


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
        # Per-workout detail cache persisted across restarts so historic
        # picks don't burn an API call after every reboot. Written via
        # ``async_delay_save`` so backfill loops don't hit disk per-entry.
        self._details_store: Store = Store(
            hass,
            _DETAILS_SCHEMA_VERSION,
            f"{DOMAIN}_details_{entry.entry_id}",
        )
        # Serializes manifest read-modify-write across the regular poll,
        # backfill (recent + full), and cleanup paths so concurrent writers
        # don't drop each other's entries on the floor.
        self._manifest_lock = asyncio.Lock()
        # In-memory mirror of ``workouts.json``. Populated by
        # ``async_load_workouts_index`` at setup and kept in sync by
        # ``_refresh_manifest`` / ``async_cleanup_geojson``. The workout
        # picker ``SelectEntity`` reads from it so the dropdown stays
        # snappy without disk I/O on every state read.
        self._workouts_index: dict[int, dict[str, Any]] = {}

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

    async def async_load_workouts_index(self) -> None:
        """Populate the in-memory workouts index from the persisted manifest.

        Lets the workout-picker ``SelectEntity`` come up with the full
        dropdown right after restart, without waiting for the first
        regular-poll listing to round-trip. Also restores the user's
        last selection (manifest ``selected_id``) so the headline
        sensors come up pinned to the right workout.
        """
        try:
            self._workouts_index = await self.hass.async_add_executor_job(
                read_manifest_entries, self._geojson_dir
            )
        except OSError as err:
            _LOGGER.warning("Could not preload workouts index: %s", err)
            self._workouts_index = {}
        try:
            selected = await self.hass.async_add_executor_job(
                read_selected_workout_id, self._geojson_dir
            )
        except OSError as err:
            _LOGGER.warning("Could not preload selected workout id: %s", err)
            selected = None
        if selected is not None:
            self._selected_workout_id = selected

    async def async_load_details_cache(self) -> None:
        """Rehydrate the per-workout detail cache from disk.

        Setup-phase work — called after ``async_load_workouts_index``
        so a cache-only cold start (rate-limited API, no successful
        poll) can still hand the per-workout sensors a populated
        ``coordinator.data`` for the pinned selection.
        """
        try:
            payload = await self._details_store.async_load()
        except Exception as err:  # noqa: BLE001 — load failure must not block setup
            _LOGGER.warning("Could not load workout details cache: %s", err)
            return
        if not payload or not isinstance(payload, dict):
            return
        raw = payload.get("workouts")
        if not isinstance(raw, dict):
            return
        loaded = 0
        for wid_str, entry in raw.items():
            try:
                wid = int(wid_str)
            except (TypeError, ValueError):
                continue
            data = workout_data_from_storage(entry)
            if data is not None:
                self._detail_cache[wid] = data
                loaded += 1
        if loaded:
            _LOGGER.debug("Loaded %d workout(s) from the details cache", loaded)

    def initial_data_from_cache(self) -> WorkoutData | None:
        """Return cached ``WorkoutData`` for the restored selection, if any.

        Called by setup so the coordinator can seed ``self.data`` before
        the first refresh fires. With this, per-workout sensors come up
        populated even when the API is rate-limited at boot.
        """
        if self._selected_workout_id is None:
            return None
        return self._detail_cache.get(self._selected_workout_id)

    def _build_details_storage_payload(self) -> dict[str, Any]:
        """Snapshot the in-memory cache for ``async_delay_save``."""
        return {
            "version": _DETAILS_SCHEMA_VERSION,
            "workouts": {
                str(wid): workout_data_to_storage(wd) for wid, wd in self._detail_cache.items()
            },
        }

    def _schedule_details_save(self) -> None:
        """Coalesce backfill-rate writes into one disk hit per debounce window."""
        self._details_store.async_delay_save(
            self._build_details_storage_payload, _DETAILS_SAVE_DELAY_SECONDS
        )

    def _emit_personal_records(self, data: WorkoutData) -> None:
        """Fire an ``EVENT_PERSONAL_RECORD`` event for each new PR.

        Compares ``data`` against the historical max in the detail
        cache for the matching indoor/outdoor class. Called only from
        the polling path — backfill (``async_backfill_recent``,
        ``async_full_backfill``) populates the baseline silently so a
        cold-start full backfill doesn't dump hundreds of "records"
        onto the event bus.

        First workout in a class fires events too (per the 2026-06-14
        design decision: no warmup period). The very first ride sets
        the baseline and IS the record.
        """
        records = detect_personal_records(data, self._detail_cache.values())
        for record in records:
            self.hass.bus.async_fire(
                EVENT_PERSONAL_RECORD,
                {
                    "kind": record.kind,
                    "value": record.value,
                    "previous_value": record.previous_value,
                    "workout_id": record.workout_id,
                    "indoor": record.indoor,
                },
            )

    def known_workouts(self) -> list[dict[str, Any]]:
        """Return all known workouts sorted by ``starts`` desc (shallow copies)."""
        return sorted(
            (dict(entry) for entry in self._workouts_index.values()),
            key=lambda e: e.get("starts") or "",
            reverse=True,
        )

    def known_workout(self, workout_id: int) -> dict[str, Any] | None:
        """Look up a single workout in the index by id."""
        entry = self._workouts_index.get(workout_id)
        return dict(entry) if entry else None

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
        """Pin sensors + map to ``workout_id`` (``None`` = follow latest).

        Writes ``selected_id`` to the manifest synchronously so the viewer
        sees the new pin within its 5-second poll, then kicks off a
        background render for outdoor picks whose ``.geojson`` isn't on disk.
        """
        if workout_id == self._selected_workout_id:
            return
        self._selected_workout_id = workout_id
        # Snapshot the render decision before ``_refresh_manifest`` rebuilds
        # ``_workouts_index`` from disk — the in-memory mirror is the stable
        # read.
        should_render = self._should_render_on_select(workout_id)
        await self._refresh_manifest([], workout_id)
        if should_render:
            self.hass.async_create_task(
                self._render_selected_workout(workout_id),
                name=f"hawahooligan_render_{workout_id}",
            )
        await self.async_request_refresh()

    def _should_render_on_select(self, workout_id: int | None) -> bool:
        """Return True for picks that should trigger a background render."""
        if workout_id is None:
            return False
        entry = self._workouts_index.get(workout_id)
        if entry is None:
            # Unknown id (service call for a pre-accumulator workout): let
            # the render fetch detail and decide. Same cost as any other
            # way of finding out.
            return True
        if entry.get("indoor") or entry.get("manual"):
            return False
        return not entry.get("has_track")

    async def _render_selected_workout(self, workout_id: int) -> None:
        """Render ``<id>.geojson`` + refresh the manifest so ``has_track`` flips."""
        try:
            url = await self.async_render_workout(workout_id)
        except Exception as err:  # noqa: BLE001 — on-demand render must not crash select
            _LOGGER.warning("On-demand render for workout %d failed: %s", workout_id, err)
            return
        if url is None:
            entry = self._workouts_index.get(workout_id)
            if entry and not entry.get("indoor") and not entry.get("manual"):
                _LOGGER.warning(
                    "On-demand render for outdoor workout %d returned no track "
                    "— likely rate-limited. Retry after the next Wahoo quota "
                    "reset (Sandbox: 00:00 UTC).",
                    workout_id,
                )
            return
        await self._refresh_manifest([], self._selected_workout_id)

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

            # PR detection runs BEFORE the cache write so the new entry
            # isn't compared against itself. Backfill paths
            # (``async_backfill_recent``, ``async_full_backfill``)
            # deliberately skip the emit step — they populate the
            # baseline silently to avoid flooding the bus with hundreds
            # of stale "records" during initial bulk fetches.
            self._emit_personal_records(data)
            self._detail_cache[target_id] = data
            self._schedule_details_save()
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
            self._schedule_details_save()

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
        """Merge ``recent`` into the manifest + in-memory index; never raises.

        Held under :attr:`_manifest_lock` so a parallel ``async_full_backfill``
        / cleanup / regular poll can't drop each other's entries via a
        read-modify-write race. The lock is async-only; the disk I/O still
        runs in the executor.

        On success, ``async_update_listeners`` pushes the new index to the
        workout-picker ``SelectEntity`` so the dropdown's options refresh
        without waiting for the next poll cycle.
        """
        async with self._manifest_lock:
            try:
                merged = await self.hass.async_add_executor_job(
                    merge_and_write_manifest, self._geojson_dir, recent, selected_id
                )
            except OSError as err:
                _LOGGER.warning("Could not refresh picker manifest: %s", err)
                return
            self._workouts_index = merged
        self.async_update_listeners()

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
        self._detail_cache[workout_id] = data
        self._schedule_details_save()
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
        """Render + record-totals for the last ``count`` workouts; return new-render count.

        Skips workouts already in totals AND on disk. Budgeted against the
        Sandbox 25 / 5-min ceiling; bails after 3 consecutive 429s. Auth
        failures bubble up for HA's reauth flow.
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
        guard = ConsecutiveLimitGuard()
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
                if guard.record_failure(err.status_code):
                    _LOGGER.warning(
                        "Backfill aborting after %d consecutive 429s — Wahoo's "
                        "larger rate-limit window is exhausted; the next regular "
                        "poll will resume work once the quota recovers (Sandbox "
                        "tier resets daily at 00:00 UTC)",
                        guard.strikes,
                    )
                    break
                continue
            guard.record_success()

            data = _build_workout_data(detail)
            self._detail_cache[workout_id] = data
            self._schedule_details_save()
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
        """Paginate the user's whole Wahoo history into lifetime totals.

        ``with_tracks=True`` also renders the GeoJSON for outdoor / non-manual
        workouts. Bails after 3 consecutive 429s; auth failures bubble up as
        ``ConfigEntryAuthFailed``. Fires ``EVENT_BACKFILL_PROGRESS`` per page.
        """
        budget = RateLimitBudget(max_calls_per_window, window_seconds)
        added_total = 0
        processed_total = 0
        # Hourly / daily rate-limit exhaustion shows up as detail calls
        # 429-ing back to back — the 5-min budget slows the rolling window
        # but can't see the larger caps. Same bail-out shape as
        # ``async_backfill_recent`` uses, sharing one :class:`ConsecutiveLimitGuard`
        # instance — keeps both backfill loops honest with each other.
        guard = ConsecutiveLimitGuard()

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
                    if err.status_code == 429:
                        _LOGGER.warning(
                            "Full backfill aborting on listing 429 — Wahoo's "
                            "hourly or daily cap is exhausted. Re-run after "
                            "the next quota reset (Sandbox: 00:00 UTC daily)."
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
                        if guard.record_failure(err.status_code):
                            _LOGGER.warning(
                                "Full backfill aborting after %d consecutive "
                                "429s — Wahoo's hourly or daily cap is "
                                "exhausted. %d workouts already added; "
                                "re-run after the next quota reset (Sandbox: "
                                "00:00 UTC daily) to pick up where we left "
                                "off — workouts already in the totals are "
                                "skipped automatically.",
                                guard.strikes,
                                added_total,
                            )
                            self._emit_backfill_event(
                                page=page,
                                processed=processed_total,
                                added=added_total,
                                done=True,
                            )
                            return added_total
                        continue
                    guard.record_success()

                    data = _build_workout_data(detail)
                    self._detail_cache[workout_id] = data
                    self._schedule_details_save()
                    if workout_id not in self._totals.workouts and await self._record_totals(data):
                        added_total += 1
                        page_added += 1

                    if with_tracks and data.file_url and not data.manual and not data.indoor:
                        await self._render(data.workout_id, data.file_url)

                # Feed this page's listing into the picker manifest so the
                # viewer dropdown grows live during the backfill — without
                # this the dropdown would stay at the last 20 entries that
                # the regular poll knows about.
                recent_page = _build_recent_from_listing(workouts, self._geojson_dir)
                await self._refresh_manifest(recent_page, self._selected_workout_id)

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

    async def async_cleanup_geojson(self, max_age_days: int) -> int:
        """Prune ``<id>.geojson`` files older than ``max_age_days`` + sync the manifest.

        The cache (``<config>/www/hawahooligan/``) grows with every backfill
        and ``render_workout`` call. The matching picker-manifest entries
        get dropped in lockstep so the viewer dropdown doesn't list rides
        whose tracks have just vanished. Indoor / manual entries (which
        never produce a track) are untouched — they don't have a file to
        time-check.

        ``max_age_days`` must be >= 1 — the service-layer schema rejects
        anything below.

        Returns the number of removed files.
        """
        cutoff_epoch = time.time() - max_age_days * 86400
        removed_ids: set[int] = await self.hass.async_add_executor_job(
            _cleanup_geojson, self._geojson_dir, cutoff_epoch
        )
        if removed_ids:
            async with self._manifest_lock:
                try:
                    remaining = await self.hass.async_add_executor_job(
                        prune_manifest,
                        self._geojson_dir,
                        removed_ids,
                        self._selected_workout_id,
                    )
                except OSError as err:
                    _LOGGER.warning(
                        "Cleanup deleted %d file(s) but could not prune the picker manifest: %s",
                        len(removed_ids),
                        err,
                    )
                else:
                    self._workouts_index = remaining
            self.async_update_listeners()
            _LOGGER.info(
                "Cleanup: removed %d GeoJSON file(s) older than %d day(s)",
                len(removed_ids),
                max_age_days,
            )
        return len(removed_ids)

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
