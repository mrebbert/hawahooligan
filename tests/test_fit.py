"""Tier-1 unit tests for ``fit.py`` (pure FIT → GeoJSON conversion)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import fitdecode
import pytest
from fit import (  # type: ignore[import-not-found]
    _SC_TO_DEG,
    parse_fit_to_geojson,
    write_geojson,
)


class _FakeFrame:
    """Mimic the parts of ``fitdecode.FitDataMessage`` that ``fit.py`` reads."""

    def __init__(self, name: str, fields: dict[str, int | None] | None = None) -> None:
        self.name = name
        self._fields = fields or {}

    def get_value(self, key: str, fallback: object = None) -> object:
        return self._fields.get(key, fallback)


class _FakeReader:
    """Drop-in for ``fitdecode.FitReader`` as a context manager + iterable."""

    def __init__(self, frames: list[object]) -> None:
        self._frames = frames

    def __enter__(self) -> _FakeReader:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __iter__(self):
        return iter(self._frames)


# A real FitDataMessage in fitdecode is an instance check target. We patch
# ``fitdecode.FitDataMessage`` to a tuple including our fake type so the
# ``isinstance`` check inside ``fit.py`` recognizes them.
@pytest.fixture
def patched_message_type():
    with patch.object(fitdecode, "FitDataMessage", new=(fitdecode.FitDataMessage, _FakeFrame)):
        yield


def _semicircle(deg: float) -> int:
    """Inverse of the conversion ``fit.py`` applies."""
    return int(round(deg / _SC_TO_DEG))


class TestParseFitToGeojson:
    def test_returns_none_for_indoor_workout_without_gps(self, patched_message_type: None) -> None:
        # Records exist but none carry coordinates → indoor / lost-GPS case.
        frames = [
            _FakeFrame("file_id"),
            _FakeFrame("record", {"position_lat": None, "position_long": None}),
            _FakeFrame("record", {"position_lat": None, "position_long": None}),
        ]
        with patch.object(fitdecode, "FitReader", lambda _: _FakeReader(frames)):
            assert parse_fit_to_geojson(b"\x00") is None

    def test_returns_none_for_single_point(self, patched_message_type: None) -> None:
        frames = [
            _FakeFrame(
                "record",
                {"position_lat": _semicircle(52.5), "position_long": _semicircle(13.4)},
            )
        ]
        with patch.object(fitdecode, "FitReader", lambda _: _FakeReader(frames)):
            assert parse_fit_to_geojson(b"\x00") is None

    def test_converts_semicircles_and_emits_lon_lat_pairs(self, patched_message_type: None) -> None:
        # Brandenburg Gate (52.5163, 13.3777) and Reichstag (52.5186, 13.3762).
        coords_deg = [(52.5163, 13.3777), (52.5186, 13.3762)]
        frames = [
            _FakeFrame(
                "record",
                {"position_lat": _semicircle(lat), "position_long": _semicircle(lon)},
            )
            for lat, lon in coords_deg
        ]
        with patch.object(fitdecode, "FitReader", lambda _: _FakeReader(frames)):
            feature = parse_fit_to_geojson(b"\x00")

        assert feature is not None
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "LineString"
        assert feature["properties"]["point_count"] == 2

        # Coordinates must be [lon, lat] (longitude first per RFC 7946).
        for (expected_lat, expected_lon), point in zip(
            coords_deg, feature["geometry"]["coordinates"], strict=True
        ):
            lon, lat = point
            assert lon == pytest.approx(expected_lon, abs=1e-6)
            assert lat == pytest.approx(expected_lat, abs=1e-6)

    def test_skips_non_record_messages(self, patched_message_type: None) -> None:
        frames = [
            _FakeFrame("file_id"),
            _FakeFrame(
                "record",
                {"position_lat": _semicircle(0.0), "position_long": _semicircle(0.0)},
            ),
            _FakeFrame("session", {"position_lat": 999, "position_long": 999}),
            _FakeFrame(
                "record",
                {"position_lat": _semicircle(1.0), "position_long": _semicircle(1.0)},
            ),
        ]
        with patch.object(fitdecode, "FitReader", lambda _: _FakeReader(frames)):
            feature = parse_fit_to_geojson(b"\x00")
        assert feature is not None
        assert feature["properties"]["point_count"] == 2

    def test_returns_none_on_fit_decode_error(self, patched_message_type: None) -> None:
        class _BoomReader(_FakeReader):
            def __enter__(self) -> _FakeReader:
                raise fitdecode.FitError("malformed payload")

        with patch.object(fitdecode, "FitReader", lambda _: _BoomReader([])):
            assert parse_fit_to_geojson(b"\x00") is None


class TestWriteGeojson:
    def test_writes_per_workout_and_latest_files(self, tmp_path: Path) -> None:
        feature = {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[13.4, 52.5], [13.5, 52.6]]},
            "properties": {"point_count": 2},
        }
        workout_path = write_geojson(tmp_path / "www" / "hawahooligan", 12345, feature)

        assert workout_path.name == "12345.geojson"
        assert workout_path.exists()
        assert json.loads(workout_path.read_text()) == feature

        latest = workout_path.parent / "latest.geojson"
        assert latest.exists()
        assert json.loads(latest.read_text()) == feature

    def test_creates_missing_directories(self, tmp_path: Path) -> None:
        feature = {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            "properties": {"point_count": 2},
        }
        target = tmp_path / "nested" / "tree" / "www" / "hawahooligan"
        write_geojson(target, "abc", feature)
        assert (target / "abc.geojson").exists()
