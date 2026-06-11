"""Tier-1 tests for the picker manifest accumulator (``manifest.py``).

The module is HA-free by design — these tests load it directly via the
``_load`` trick in ``conftest.py``. We exercise:

- read tolerance against missing / malformed payloads
- write → read round-trip including ``has_track`` filesystem refresh
- atomic write (tmp + os.replace) leaves no ``*.tmp`` behind on success
- merge unions new with existing without dropping any id
- merge preserves a previously stored ``duration_min`` when the new
  listing omits it
- prune drops only the requested ids
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from manifest import (  # type: ignore[import-not-found]
    MANIFEST_FILENAME,
    RecentWorkout,
    merge_and_write_manifest,
    persist_manifest_atomic,
    prune_manifest,
    read_manifest_entries,
)


def _outdoor(
    id: int, *, starts: str, name: str = "Ride", duration_min: float | None = None
) -> RecentWorkout:
    return RecentWorkout(
        id=id,
        name=name,
        starts=starts,
        workout_type_id=0,
        workout_type_name="Biking",
        indoor=False,
        manual=False,
        has_track=False,  # rewritten from filesystem on write
        duration_min=duration_min,
    )


def _seed_geojson(directory: Path, workout_id: int) -> Path:
    path = directory / f"{workout_id}.geojson"
    path.write_text("{}", encoding="utf-8")
    return path


class TestReadManifestEntries:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert read_manifest_entries(tmp_path) == {}

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / MANIFEST_FILENAME).write_text("not json", encoding="utf-8")
        assert read_manifest_entries(tmp_path) == {}

    def test_payload_without_workouts_list_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / MANIFEST_FILENAME).write_text(
            json.dumps({"selected_id": None}), encoding="utf-8"
        )
        assert read_manifest_entries(tmp_path) == {}

    def test_skips_non_integer_ids_and_non_dict_entries(self, tmp_path: Path) -> None:
        (tmp_path / MANIFEST_FILENAME).write_text(
            json.dumps(
                {
                    "workouts": [
                        {"id": 1, "name": "kept"},
                        {"id": "two", "name": "dropped"},  # string id
                        "not-a-dict",
                        {"name": "missing id"},
                    ],
                    "selected_id": None,
                }
            ),
            encoding="utf-8",
        )
        result = read_manifest_entries(tmp_path)
        assert list(result.keys()) == [1]


class TestPersistManifestAtomic:
    def test_roundtrip_preserves_entries(self, tmp_path: Path) -> None:
        """Round-trip preserves all caller fields; ``has_track`` is added by the writer."""
        original = {1: {"id": 1, "name": "Roundtrip", "starts": "2026-06-10T07:00:00Z"}}
        persist_manifest_atomic(tmp_path, original, selected_id=1)
        round_tripped = read_manifest_entries(tmp_path)
        assert round_tripped[1]["id"] == 1
        assert round_tripped[1]["name"] == "Roundtrip"
        assert round_tripped[1]["starts"] == "2026-06-10T07:00:00Z"
        # ``has_track`` is always derived from the filesystem on write.
        assert round_tripped[1]["has_track"] is False

    def test_writes_via_tmp_then_replace(self, tmp_path: Path) -> None:
        """No ``*.tmp`` sidecar must survive a successful call.

        Sanity-flip: removing the ``os.replace`` step in
        ``persist_manifest_atomic`` makes this assertion go red because
        the tmp file would stick around (or the target would never appear).
        """
        persist_manifest_atomic(tmp_path, {42: {"id": 42}}, selected_id=None)
        assert (tmp_path / MANIFEST_FILENAME).is_file()
        assert not (tmp_path / f"{MANIFEST_FILENAME}.tmp").exists()

    def test_has_track_derived_from_filesystem(self, tmp_path: Path) -> None:
        """An entry's ``has_track`` is always re-derived from disk on write."""
        # Seed two entries; only one has a file on disk.
        _seed_geojson(tmp_path, 1)
        entries = {
            1: {"id": 1, "name": "with file", "has_track": False},
            2: {"id": 2, "name": "without file", "has_track": True},  # lie — gets fixed
        }
        persist_manifest_atomic(tmp_path, entries, selected_id=None)
        round_tripped = read_manifest_entries(tmp_path)
        assert round_tripped[1]["has_track"] is True
        assert round_tripped[2]["has_track"] is False

    def test_does_not_mutate_caller_entries(self, tmp_path: Path) -> None:
        """The defensive ``dict(entry)`` copy must keep the caller's dict pristine."""
        entries = {1: {"id": 1, "has_track": False}}
        persist_manifest_atomic(tmp_path, entries, selected_id=None)
        # Caller's dict still has the original ``has_track`` value — the
        # filesystem-derived one only lands in the serialized payload.
        assert entries[1]["has_track"] is False


class TestMergeAndWriteManifest:
    def test_unions_new_workouts_with_existing(self, tmp_path: Path) -> None:
        # Seed with an older entry that should survive the merge.
        persist_manifest_atomic(
            tmp_path,
            {100: {"id": 100, "name": "Old", "starts": "2026-05-01T00:00:00Z"}},
            selected_id=None,
        )
        merged = merge_and_write_manifest(
            tmp_path,
            [_outdoor(200, starts="2026-06-01T00:00:00Z", name="New")],
            selected_id=None,
        )
        assert set(merged.keys()) == {100, 200}, "merge must keep old AND add new"

    def test_preserves_duration_min_when_listing_omits_it(self, tmp_path: Path) -> None:
        """A listing without ``duration_active_accum`` shouldn't drop a known duration."""
        persist_manifest_atomic(
            tmp_path,
            {7: {"id": 7, "name": "Has duration", "duration_min": 90.0}},
            selected_id=None,
        )
        merge_and_write_manifest(
            tmp_path,
            [_outdoor(7, starts="2026-06-01T00:00:00Z", name="Has duration", duration_min=None)],
            selected_id=None,
        )
        round_tripped = read_manifest_entries(tmp_path)
        assert round_tripped[7]["duration_min"] == 90.0

    def test_returns_in_memory_index(self, tmp_path: Path) -> None:
        """Return value lets the caller mirror state without a second read."""
        merged = merge_and_write_manifest(
            tmp_path,
            [_outdoor(11, starts="2026-06-01T00:00:00Z")],
            selected_id=11,
        )
        on_disk = read_manifest_entries(tmp_path)
        assert merged == on_disk


class TestPruneManifest:
    def test_drops_only_requested_ids(self, tmp_path: Path) -> None:
        persist_manifest_atomic(
            tmp_path,
            {
                1: {"id": 1, "name": "keep"},
                2: {"id": 2, "name": "drop"},
                3: {"id": 3, "name": "keep"},
            },
            selected_id=None,
        )
        remaining = prune_manifest(tmp_path, {2}, selected_id=None)
        assert set(remaining.keys()) == {1, 3}
        assert set(read_manifest_entries(tmp_path).keys()) == {1, 3}

    def test_empty_removed_set_is_noop(self, tmp_path: Path) -> None:
        persist_manifest_atomic(
            tmp_path,
            {1: {"id": 1, "name": "keep"}},
            selected_id=None,
        )
        remaining = prune_manifest(tmp_path, set(), selected_id=None)
        assert list(remaining.keys()) == [1]

    @pytest.mark.parametrize("missing_id", [9999, -1, 0])
    def test_unknown_ids_are_silently_ignored(self, tmp_path: Path, missing_id: int) -> None:
        persist_manifest_atomic(
            tmp_path,
            {1: {"id": 1, "name": "keep"}},
            selected_id=None,
        )
        # Mixing a real id with unknowns — only the real one drops.
        remaining = prune_manifest(tmp_path, {1, missing_id}, selected_id=None)
        assert remaining == {}
