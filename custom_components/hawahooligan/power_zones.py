"""Wahoo power-zones parser.

Pure module — no Home Assistant imports — so it's trivially testable in
Tier-1 via the same ``importlib`` trick the FIT parser uses.

``GET /v1/power_zones`` returns an array of zone records. A user typically
has one record per sport (Biking, Running, …); the one we expose is the
"primary" entry — the most-recently-updated record with a non-zero FTP.
That's also the record Wahoo's own apps treat as authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class PowerZonesData:
    """Headline FTP / critical-power numbers + the zone-boundary table.

    Wahoo reports each zone field as an absolute power value in watts, not
    as a percentage of FTP or a min/max range. We expose the same shape so
    automations can directly reference ``zone_5`` etc.
    """

    record_id: int | None = None
    ftp: float | None = None
    critical_power: float | None = None
    zone_count: int | None = None
    zone_1: float | None = None
    zone_2: float | None = None
    zone_3: float | None = None
    zone_4: float | None = None
    zone_5: float | None = None
    zone_6: float | None = None
    zone_7: float | None = None
    workout_type_id: int | None = None
    workout_type_family_id: int | None = None
    updated_at: str | None = None

    @property
    def zone_list(self) -> list[float | None]:
        return [
            self.zone_1,
            self.zone_2,
            self.zone_3,
            self.zone_4,
            self.zone_5,
            self.zone_6,
            self.zone_7,
        ]


def _build(record: dict[str, Any]) -> PowerZonesData:
    return PowerZonesData(
        record_id=_as_int(record.get("id")),
        ftp=_as_float(record.get("ftp")),
        critical_power=_as_float(record.get("critical_power")),
        zone_count=_as_int(record.get("zone_count")),
        zone_1=_as_float(record.get("zone_1")),
        zone_2=_as_float(record.get("zone_2")),
        zone_3=_as_float(record.get("zone_3")),
        zone_4=_as_float(record.get("zone_4")),
        zone_5=_as_float(record.get("zone_5")),
        zone_6=_as_float(record.get("zone_6")),
        zone_7=_as_float(record.get("zone_7")),
        workout_type_id=_as_int(record.get("workout_type_id")),
        workout_type_family_id=_as_int(record.get("workout_type_family_id")),
        updated_at=record.get("updated_at"),
    )


def parse_power_zones(response: Any) -> PowerZonesData | None:
    """Pick the primary zone record from ``GET /v1/power_zones``.

    Returns ``None`` if the response is empty (the user has never run an FTP
    test) or malformed. With multiple records we prefer the one with a
    non-zero FTP and the latest ``updated_at`` — Wahoo's apps consider that
    the canonical profile.
    """
    if not isinstance(response, list) or not response:
        return None

    candidates = [_build(r) for r in response if isinstance(r, dict)]
    if not candidates:
        return None

    with_ftp = [c for c in candidates if c.ftp is not None and c.ftp > 0]
    pool = with_ftp or candidates
    pool.sort(key=lambda r: r.updated_at or "", reverse=True)
    return pool[0]
