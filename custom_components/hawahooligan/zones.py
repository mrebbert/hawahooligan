"""Coggan power-zone defaults derived from FTP.

Pure module — no Home Assistant imports — so it's trivially testable
in Tier-1 via the same ``importlib`` trick the FIT parser uses.

The seven-zone Coggan model is the canonical training-load
classification used by TrainingPeaks, the Wahoo App, and most modern
cycling-power systems. Each zone is expressed as a percentage of FTP
(functional threshold power), and the value HAWahooligan ships to
Wahoo is the UPPER boundary of the zone in absolute watts.

Reference (Dr Andrew Coggan, "Training and Racing with a Power
Meter", 3rd ed.):

  Zone 1 — Active Recovery    < 55%
  Zone 2 — Endurance        55–75%
  Zone 3 — Tempo            76–90%
  Zone 4 — Lactate Threshold 91–105%
  Zone 5 — VO2max          106–120%
  Zone 6 — Anaerobic       121–150%
  Zone 7 — Neuromuscular    >150%

Zone 7 has no real upper bound — humans run out of sprint capacity
long before they run out of power. We pick 1.95× FTP as a defensible
"sprint ceiling" so Wahoo gets a finite number; users who want a
different cap can pass their own ``zone_7`` to the service.
"""

from __future__ import annotations

from dataclasses import dataclass

# Upper boundaries of each zone, as multipliers of FTP. Order matters —
# the tuple index + 1 is the zone number.
_COGGAN_FACTORS: tuple[float, ...] = (
    0.55,  # Z1
    0.75,  # Z2
    0.90,  # Z3
    1.05,  # Z4
    1.20,  # Z5
    1.50,  # Z6
    1.95,  # Z7 — sprint-ceiling sentinel; arbitrary but defensible
)


@dataclass(slots=True, frozen=True)
class CogganZones:
    """Seven absolute-watts zone boundaries.

    All seven values are required by Wahoo's POST /v1/power_zones
    payload, so the dataclass mirrors that shape. Float rather than
    int because integer rounding at low FTP values (e.g. FTP 100 →
    0.55 × 100 = 55 exactly, but FTP 220 → 0.55 × 220 = 121 vs
    121.0) is irrelevant to Wahoo — they accept both.
    """

    zone_1: float
    zone_2: float
    zone_3: float
    zone_4: float
    zone_5: float
    zone_6: float
    zone_7: float

    def as_dict(self) -> dict[str, float]:
        """Return ``{"zone_1": …, …, "zone_7": …}`` — Wahoo's payload shape."""
        return {f"zone_{i}": getattr(self, f"zone_{i}") for i in range(1, 8)}


def coggan_zones_for(ftp: float) -> CogganZones:
    """Derive the seven Coggan upper-boundary watts from ``ftp``.

    ``ftp`` is the user's functional threshold power in watts. Returns
    a :class:`CogganZones` with zones 1 through 7 rounded to the
    nearest watt — Wahoo's app rounds too, and integer-watt boundaries
    read cleaner in template sensors.
    """
    if ftp <= 0:
        raise ValueError(f"ftp must be positive, got {ftp}")
    values = tuple(round(ftp * factor) for factor in _COGGAN_FACTORS)
    return CogganZones(*values)
