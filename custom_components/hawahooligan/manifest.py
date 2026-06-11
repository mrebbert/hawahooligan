"""Picker manifest accumulator — ``<config>/www/hawahooligan/workouts.json``.

The bundled Leaflet viewer reads this file to populate its dropdown, and
the workout-picker ``SelectEntity`` mirrors it in memory. Both consumers
want the union of every workout the integration has ever seen — regular
polls add the last 20, ``full_backfill`` adds everything else, and
``cleanup_geojson`` prunes entries whose tracks were just deleted.

The module is **Home Assistant-free** so the read / write / merge /
prune contract is Tier-1 testable. The coordinator handles the
HA-coupled parts (asyncio lock, executor dispatch, listener push); this
file owns:

* the on-disk shape (`MANIFEST_FILENAME` + the JSON layout),
* the in-memory ``RecentWorkout`` dataclass used to merge new entries,
* the four pure helpers the coordinator calls into.

Atomicity: ``persist_manifest_atomic`` writes to a sidecar ``.tmp`` file
then ``os.replace``s into place. The viewer fetches ``workouts.json``
over HA's ``/local/`` static-file server; without the rename trick a
mid-write fetch would land on a partially flushed file and fail JSON
parse.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# Filename of the picker manifest under ``<config>/www/hawahooligan/``.
# Kept inside the manifest module so the on-disk shape lives next to the
# code that owns it; ``const.py`` re-exports for older import sites.
MANIFEST_FILENAME: Final = "workouts.json"


@dataclass(slots=True)
class RecentWorkout:
    """Lean summary of one entry in the rolling recent-workouts window.

    Picker UIs only need enough to render a "27 Apr — Morning ride" option
    and look up the GeoJSON on disk; the full ``WorkoutData`` is overkill
    here. ``has_track`` records whether the corresponding ``<id>.geojson``
    has actually been rendered — indoor and manual entries stay listed for
    context but mark this ``False`` so the viewer can show its overlay.
    """

    id: int
    name: str | None
    starts: str | None
    workout_type_id: int | None
    workout_type_name: str | None
    indoor: bool
    manual: bool
    has_track: bool
    duration_min: float | None = None


def read_selected_workout_id(directory: Path) -> int | None:
    """Blocking: pull just ``selected_id`` out of the manifest.

    Returns ``None`` if the manifest is missing, malformed, or the
    selected_id field isn't an int. Lets the coordinator restore the
    user's "currently pinned" workout across HA restarts without
    parsing the full workouts dict.
    """
    path = directory / MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    sel = payload.get("selected_id")
    return sel if isinstance(sel, int) else None


def read_manifest_entries(directory: Path) -> dict[int, dict[str, Any]]:
    """Blocking: load the existing manifest, return ``{workout_id: entry}``.

    Returns ``{}`` if the manifest is missing or malformed — the caller
    rebuilds from the next listing, no data loss beyond the bad payload.
    Lenient against schema drift: non-dict entries and entries with
    non-integer ids are silently skipped rather than raising.
    """
    path = directory / MANIFEST_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    workouts = payload.get("workouts") if isinstance(payload, dict) else None
    if not isinstance(workouts, list):
        return {}
    result: dict[int, dict[str, Any]] = {}
    for entry in workouts:
        if not isinstance(entry, dict):
            continue
        wid = entry.get("id")
        if isinstance(wid, int):
            result[wid] = entry
    return result


def persist_manifest_atomic(
    directory: Path,
    entries_by_id: dict[int, dict[str, Any]],
    selected_id: int | None,
) -> None:
    """Blocking: serialize the manifest via tmp + ``os.replace``.

    Always refreshes ``has_track`` from the filesystem so a deleted track
    (cleanup, manual rm) flips the flag automatically without the caller
    needing to remember.
    """
    directory.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for entry in entries_by_id.values():
        # Defensive copy — never mutate the caller's dict.
        out = dict(entry)
        out["has_track"] = (directory / f"{out['id']}.geojson").is_file()
        entries.append(out)
    entries.sort(key=lambda e: e.get("starts") or "", reverse=True)
    payload = json.dumps(
        {"workouts": entries, "selected_id": selected_id},
        separators=(",", ":"),
    )
    target = directory / MANIFEST_FILENAME
    tmp = directory / f"{MANIFEST_FILENAME}.tmp"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, target)


def merge_and_write_manifest(
    directory: Path,
    recent: list[RecentWorkout],
    selected_id: int | None,
) -> dict[int, dict[str, Any]]:
    """Blocking: union ``recent`` into the existing manifest, return merged set.

    Older entries stay unless ``prune_manifest`` removes them — that's the
    load-bearing piece that lets ``full_backfill`` / a long-running install
    accumulate hundreds of workouts in the dropdown instead of just the
    last 20 the recent-poll endpoint returns.

    Returning the merged ``{id: entry}`` dict lets the caller mirror the
    current manifest into in-memory state without a second read-from-disk —
    the workout picker entity needs that for its ``options`` property.
    """
    entries_by_id = read_manifest_entries(directory)
    for r in recent:
        new_entry: dict[str, Any] = {
            "id": r.id,
            "name": r.name,
            "starts": r.starts,
            "workout_type_id": r.workout_type_id,
            "workout_type": r.workout_type_name,
            "indoor": r.indoor,
            "manual": r.manual,
            # Re-derived by ``persist_manifest_atomic`` from the
            # filesystem, but set here so debug-mode JSON dumps in the
            # executor look sane.
            "has_track": (directory / f"{r.id}.geojson").is_file(),
        }
        if r.duration_min is not None:
            new_entry["duration_min"] = r.duration_min
        else:
            # Preserve any older duration we'd previously stored for this id
            # — the listing endpoint occasionally omits
            # ``duration_active_accum`` but the detail endpoint had it
            # during render time.
            existing = entries_by_id.get(r.id, {})
            if "duration_min" in existing:
                new_entry["duration_min"] = existing["duration_min"]
        entries_by_id[r.id] = new_entry
    persist_manifest_atomic(directory, entries_by_id, selected_id)
    return entries_by_id


def prune_manifest(
    directory: Path,
    removed_ids: set[int],
    selected_id: int | None,
) -> dict[int, dict[str, Any]]:
    """Blocking: drop ``removed_ids`` from the manifest, return what's left."""
    entries_by_id = read_manifest_entries(directory)
    for wid in removed_ids:
        entries_by_id.pop(wid, None)
    persist_manifest_atomic(directory, entries_by_id, selected_id)
    return entries_by_id
