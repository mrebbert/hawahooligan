"""Wahoo-style power-zone defaults derived from FTP.

Factors reverse-engineered from the Wahoo app's auto-derivation
(FTP=229 → boundaries match within 1W rounding). Matching the app's
formula matters because zone-time analytics in ELEMNT/SYSTM anchor
on these specific boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass

# Upper boundary of each zone as a multiplier of FTP. Index + 1 = zone number.
_WAHOO_FACTORS: tuple[float, ...] = (
    0.55,  # Z1 Recovery
    0.70,  # Z2 Endurance
    0.91,  # Z3 Tempo
    0.96,  # Z4 Sub-threshold (NOTE: below FTP)
    1.03,  # Z5 Threshold (narrow band straddling FTP)
    1.20,  # Z6 Anaerobic
    5.00,  # Z7 Neuromuscular sentinel — Z7 has no real upper bound
)


@dataclass(slots=True, frozen=True)
class DefaultZones:
    """Seven absolute-watts zone boundaries — Wahoo POST /v1/power_zones payload shape."""

    zone_1: float
    zone_2: float
    zone_3: float
    zone_4: float
    zone_5: float
    zone_6: float
    zone_7: float

    def as_dict(self) -> dict[str, float]:
        return {f"zone_{i}": getattr(self, f"zone_{i}") for i in range(1, 8)}


def default_zones_for(ftp: float) -> DefaultZones:
    """Round-to-watt upper boundaries derived from ``ftp`` via the Wahoo factors."""
    if ftp <= 0:
        raise ValueError(f"ftp must be positive, got {ftp}")
    values = tuple(round(ftp * factor) for factor in _WAHOO_FACTORS)
    return DefaultZones(*values)
