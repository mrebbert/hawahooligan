"""FIT-file → GeoJSON LineString conversion.

Pure-Python: no Home Assistant imports here so the module is trivially
importable in Tier-1 unit tests. Runs blocking I/O (``fitdecode`` reads the
whole file synchronously) — callers must dispatch via
``hass.async_add_executor_job``.

The Wahoo Cloud API delivers FIT files with positions encoded as 32-bit
semicircles. The conversion factor is ``180 / 2**31`` degrees per semicircle.
GeoJSON requires coordinates in ``[longitude, latitude]`` order (longitude
FIRST) — a common source of bugs when wiring up map layers.
"""

from __future__ import annotations

import json
import logging
import warnings
from io import BytesIO
from pathlib import Path
from typing import Any

import fitdecode

_LOGGER = logging.getLogger(__name__)

# 180 / 2**31 — semicircle → degree
_SC_TO_DEG = 180.0 / (1 << 31)


def _coords_from_record(frame: fitdecode.FitDataMessage) -> tuple[float, float] | None:
    """Return ``(lon, lat)`` for a ``record`` frame, or ``None`` if it has no fix."""
    lat = frame.get_value("position_lat", fallback=None)
    lon = frame.get_value("position_long", fallback=None)
    if lat is None or lon is None:
        return None
    return (lon * _SC_TO_DEG, lat * _SC_TO_DEG)


def parse_fit_to_geojson(payload: bytes) -> dict[str, Any] | None:
    """Parse a FIT byte payload into a GeoJSON ``Feature`` (LineString).

    Returns ``None`` when the file contains fewer than two GPS-tagged records —
    that's the legitimate outcome for indoor trainers, manual entries, or any
    workout where the head unit lost GPS for the entire ride. Callers should
    treat this as "nothing to write" rather than an error.
    """
    coordinates: list[tuple[float, float]] = []
    try:
        # Wahoo FITs often carry developer-defined fields whose schema
        # fitdecode flags as missing ``native_field_num``. The decoder
        # gracefully inserts placeholder dev data, so the warning is
        # informational; we mute it to keep the HA log clean.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning, module=r"fitdecode\..*")
            with fitdecode.FitReader(BytesIO(payload)) as reader:
                for frame in reader:
                    if not isinstance(frame, fitdecode.FitDataMessage):
                        continue
                    if frame.name != "record":
                        continue
                    point = _coords_from_record(frame)
                    if point is not None:
                        coordinates.append(point)
    except fitdecode.FitError as err:
        _LOGGER.warning("FIT decoding failed: %s", err)
        return None

    if len(coordinates) < 2:
        return None

    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [list(point) for point in coordinates],
        },
        "properties": {
            "point_count": len(coordinates),
        },
    }


def write_geojson(directory: Path, workout_id: int | str, feature: dict[str, Any]) -> Path:
    """Write ``feature`` to ``<directory>/<workout_id>.geojson`` and refresh ``latest.geojson``.

    The directory is created if missing. Returns the per-workout file path.
    The caller is responsible for blocking-io context (executor).
    """
    directory.mkdir(parents=True, exist_ok=True)
    workout_path = directory / f"{workout_id}.geojson"
    payload = json.dumps(feature, separators=(",", ":"))
    workout_path.write_text(payload, encoding="utf-8")
    (directory / "latest.geojson").write_text(payload, encoding="utf-8")
    return workout_path
