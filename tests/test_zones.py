"""Tier-1 unit tests for ``zones.py`` (Wahoo-style power-zone derivation)."""

from __future__ import annotations

import pytest
from zones import (  # type: ignore[import-not-found]
    DefaultZones,
    default_zones_for,
)


class TestDefaultZonesFor:
    def test_ftp_229_matches_wahoo_app_auto_derivation(self) -> None:
        """The reference data point from a live Wahoo install.

        User-reported on 2026-06-14: entering FTP=229 W in the Wahoo
        companion app and tapping "auto-derive" produces exactly these
        seven upper boundaries. Pinning the match guards against the
        formulas drifting from what Wahoo's training tools expect.
        """
        z = default_zones_for(229)
        assert z.zone_1 == 126
        assert z.zone_2 == 160
        assert z.zone_3 == 208
        assert z.zone_4 == 220
        assert z.zone_5 == 236
        assert z.zone_6 == 275
        assert z.zone_7 == 1145

    def test_zones_are_monotonically_increasing(self) -> None:
        """No zone boundary can be ≤ the previous one — automation-breaking otherwise."""
        z = default_zones_for(250)
        as_list = [z.zone_1, z.zone_2, z.zone_3, z.zone_4, z.zone_5, z.zone_6, z.zone_7]
        for prev, cur in zip(as_list, as_list[1:], strict=False):
            assert cur > prev, f"zone boundary regression: {prev} -> {cur}"

    def test_wahoo_z4_ends_below_ftp(self) -> None:
        """Wahoo's distinguishing feature: Z4 upper sits BELOW FTP.

        Coggan models put Z4 (Lactate Threshold) at 91-105% FTP. Wahoo
        treats Z4 as the sub-threshold band (91-96%) and Z5 as the
        narrow threshold sliver straddling FTP. Pinning this guards
        against an accidental Coggan-fication of the defaults.
        """
        ftp = 250
        z = default_zones_for(ftp)
        assert z.zone_4 < ftp, (
            f"Wahoo Z4 upper ({z.zone_4}) must sit below FTP ({ftp}). "
            "If this asserts, the defaults have drifted toward Coggan."
        )

    @pytest.mark.parametrize("ftp", [100, 150, 200, 229, 250, 300, 350])
    def test_scales_linearly_with_ftp(self, ftp: float) -> None:
        """Doubling FTP doubles every boundary. Pure proportionality."""
        z1 = default_zones_for(ftp)
        z2 = default_zones_for(ftp * 2)
        for i in range(1, 8):
            f1 = getattr(z1, f"zone_{i}") * 2
            f2 = getattr(z2, f"zone_{i}")
            assert abs(f1 - f2) <= 1, (
                f"zone_{i} drift > 1W between {ftp} and {ftp * 2}: {f1} vs {f2}"
            )

    def test_zero_ftp_raises(self) -> None:
        """A user setting FTP=0 would produce all-zero zones, which is useless."""
        with pytest.raises(ValueError):
            default_zones_for(0)

    def test_negative_ftp_raises(self) -> None:
        """Defensive — negative FTP is nonsensical and would invert ordering."""
        with pytest.raises(ValueError):
            default_zones_for(-100)

    def test_float_ftp_works(self) -> None:
        """Wahoo accepts float FTP values; we shouldn't choke on 247.5."""
        z = default_zones_for(247.5)
        # 0.55 * 247.5 = 136.125 → 136
        assert z.zone_1 == 136


class TestDefaultZonesAsDict:
    def test_as_dict_returns_wahoo_payload_shape(self) -> None:
        """The dict shape matches what Wahoo's ``power_zone`` payload expects."""
        z = DefaultZones(
            zone_1=100, zone_2=200, zone_3=300, zone_4=400, zone_5=500, zone_6=600, zone_7=700
        )
        d = z.as_dict()
        assert d == {
            "zone_1": 100,
            "zone_2": 200,
            "zone_3": 300,
            "zone_4": 400,
            "zone_5": 500,
            "zone_6": 600,
            "zone_7": 700,
        }

    def test_dict_keys_are_strings_not_zone_objects(self) -> None:
        """Dict keys are strings ready for json.dumps."""
        z = default_zones_for(250)
        d = z.as_dict()
        assert all(isinstance(k, str) for k in d)
