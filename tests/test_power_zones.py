"""Tier-1 unit tests for ``power_zones.py``."""

from __future__ import annotations

from power_zones import PowerZonesData, parse_power_zones  # type: ignore[import-not-found]


def _record(**overrides) -> dict:
    base = {
        "id": 1,
        "user_id": 42,
        "ftp": 250,
        "critical_power": 270,
        "zone_count": 7,
        "zone_1": 130,
        "zone_2": 175,
        "zone_3": 230,
        "zone_4": 270,
        "zone_5": 305,
        "zone_6": 360,
        "zone_7": 450,
        "workout_type_id": 15,
        "workout_type_family_id": 1,
        "updated_at": "2026-05-01T10:00:00Z",
    }
    base.update(overrides)
    return base


class TestParsePowerZones:
    def test_empty_response_returns_none(self) -> None:
        assert parse_power_zones([]) is None
        assert parse_power_zones(None) is None
        assert parse_power_zones({"not": "a list"}) is None

    def test_single_record_is_passed_through(self) -> None:
        data = parse_power_zones([_record()])
        assert isinstance(data, PowerZonesData)
        assert data.ftp == 250
        assert data.critical_power == 270
        assert data.zone_list == [130, 175, 230, 270, 305, 360, 450]
        assert data.workout_type_family_id == 1

    def test_multiple_records_prefer_latest_updated_at(self) -> None:
        older = _record(id=1, ftp=240, updated_at="2026-04-01T10:00:00Z")
        newer = _record(id=2, ftp=260, updated_at="2026-05-15T10:00:00Z")
        data = parse_power_zones([older, newer])
        assert data is not None
        assert data.record_id == 2
        assert data.ftp == 260

    def test_records_without_ftp_are_secondary(self) -> None:
        # Two records: a "real" one with FTP and a stale one with ftp=0.
        zero = _record(id=1, ftp=0, updated_at="2026-12-31T00:00:00Z")
        real = _record(id=2, ftp=240, updated_at="2026-05-01T10:00:00Z")
        data = parse_power_zones([zero, real])
        assert data is not None
        assert data.record_id == 2
        assert data.ftp == 240

    def test_only_zero_ftp_records_returns_them_anyway(self) -> None:
        # If literally every record has ftp=0 we still surface one — better
        # than an unknown sensor when the user has a profile but never
        # tested.
        data = parse_power_zones([_record(ftp=0)])
        assert data is not None
        assert data.ftp == 0

    def test_malformed_entries_are_skipped(self) -> None:
        data = parse_power_zones([_record(), "garbage", None, 42])
        assert data is not None
        assert data.ftp == 250

    def test_string_numbers_are_coerced(self) -> None:
        data = parse_power_zones([_record(ftp="240", zone_1="125")])
        assert data is not None
        assert data.ftp == 240
        assert data.zone_1 == 125
