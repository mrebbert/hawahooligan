"""Tier-1 unit tests for ``zones.py`` (Coggan power-zone derivation)."""

from __future__ import annotations

import pytest
from zones import (  # type: ignore[import-not-found]
    CogganZones,
    coggan_zones_for,
)


class TestCogganZonesFor:
    def test_ftp_250_matches_classic_coggan_table(self) -> None:
        """The reference FTP from the README example — all seven boundaries pinned."""
        z = coggan_zones_for(250)
        # 0.55 / 0.75 / 0.90 / 1.05 / 1.20 / 1.50 / 1.95 × 250
        assert z.zone_1 == 138  # 137.5 → 138
        assert z.zone_2 == 188  # 187.5 → 188
        assert z.zone_3 == 225
        assert z.zone_4 == 262  # 262.5 → 262 (banker's rounding)
        assert z.zone_5 == 300
        assert z.zone_6 == 375
        assert z.zone_7 == 488  # 487.5 → 488

    def test_zones_are_monotonically_increasing(self) -> None:
        """No zone boundary can be ≤ the previous one — automation-breaking otherwise."""
        z = coggan_zones_for(250)
        as_list = [z.zone_1, z.zone_2, z.zone_3, z.zone_4, z.zone_5, z.zone_6, z.zone_7]
        for prev, cur in zip(as_list, as_list[1:], strict=False):
            assert cur > prev, f"zone boundary regression: {prev} -> {cur}"

    def test_ftp_at_threshold_is_inside_zone_4(self) -> None:
        """By Coggan's definition: FTP is the upper edge of zone 4 area.

        Pinning this guards against future code that mistakenly equates
        ``ftp`` to e.g. ``zone_3`` (a 90%-FTP threshold). 1.05× = upper
        Z4 boundary; FTP itself sits comfortably inside the Z4 band.
        """
        z = coggan_zones_for(250)
        assert z.zone_3 < 250 <= z.zone_4

    @pytest.mark.parametrize("ftp", [100, 150, 200, 250, 300, 350, 400])
    def test_scales_linearly_with_ftp(self, ftp: float) -> None:
        """Doubling FTP doubles every boundary. Pure proportionality."""
        z1 = coggan_zones_for(ftp)
        z2 = coggan_zones_for(ftp * 2)
        # Linearity check via z1+z1 vs z2; rounding can drift by 1W per zone.
        for i in range(1, 8):
            f1 = getattr(z1, f"zone_{i}") * 2
            f2 = getattr(z2, f"zone_{i}")
            assert abs(f1 - f2) <= 1, (
                f"zone_{i} drift > 1W between {ftp} and {ftp * 2}: {f1} vs {f2}"
            )

    def test_zero_ftp_raises(self) -> None:
        """A user setting FTP=0 would produce all-zero zones, which is useless."""
        with pytest.raises(ValueError):
            coggan_zones_for(0)

    def test_negative_ftp_raises(self) -> None:
        """Defensive — negative FTP is nonsensical and would invert ordering."""
        with pytest.raises(ValueError):
            coggan_zones_for(-100)

    def test_float_ftp_works(self) -> None:
        """Wahoo accepts float FTP values; we shouldn't choke on 247.5."""
        z = coggan_zones_for(247.5)
        # 0.55 * 247.5 = 136.125 → 136
        assert z.zone_1 == 136


class TestCogganZonesAsDict:
    def test_as_dict_returns_wahoo_payload_shape(self) -> None:
        """The dict shape matches what Wahoo's ``power_zone`` payload expects."""
        z = CogganZones(
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
        z = coggan_zones_for(250)
        d = z.as_dict()
        assert all(isinstance(k, str) for k in d)
