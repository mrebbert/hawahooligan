"""Wahoo-style power-zone defaults derived from FTP.

Pure module — no Home Assistant imports — so it's trivially testable
in Tier-1 via the same ``importlib`` trick the FIT parser uses.

The seven-zone model HAWahooligan ships matches what the Wahoo
companion app produces when a user enters their FTP and lets the app
auto-derive the zones. That's deliberate: ``set_power_zones`` is for
Wahoo users training on Wahoo hardware via Wahoo's apps (ELEMNT,
SYSTM, etc.), and the zone-time analytics in those apps anchor on
Wahoo's own boundaries. Using a different model (e.g. canonical
Andrew-Coggan ratios) would mismatch zone-time accounting for every
workout the user runs.

Reverse-engineered from a Wahoo-app data point (FTP=229 → zones
match within rounding). Each upper boundary is a fixed percentage
of FTP:

  Zone 1 — Active Recovery    ≤ 55%
  Zone 2 — Endurance        55–70%
  Zone 3 — Tempo            70–91%
  Zone 4 — Sub-threshold    91–96%
  Zone 5 — Threshold        96–103%
  Zone 6 — Anaerobic       103–120%
  Zone 7 — Neuromuscular    >120%

Notable shape: Wahoo's Z4 ends BELOW FTP (Coggan puts Z4 above), and
the supra-FTP zones are much narrower (Z5 is a ~7% sliver) — better
matched to typical indoor-training interval durations than Coggan's
physiology-band model.

Zone 7 has no real upper bound — humans run out of sprint capacity
long before they run out of power. We pick 5.00× FTP as the
sentinel; users who want a different cap can pass their own
``zone_7`` to the service.
"""

from __future__ import annotations

from dataclasses import dataclass

# Upper boundaries of each zone, as multipliers of FTP. Order matters —
# the tuple index + 1 is the zone number. Values reverse-engineered
# from Wahoo's app output for FTP=229 (matches within 1W rounding).
_WAHOO_FACTORS: tuple[float, ...] = (
    0.55,  # Z1 — Active Recovery
    0.70,  # Z2 — Endurance
    0.91,  # Z3 — Tempo (extends right up to ~FTP, unlike Coggan's 90%)
    0.96,  # Z4 — Sub-threshold (NOTE: below FTP, not above)
    1.03,  # Z5 — Threshold (narrow ~7% band straddling FTP)
    1.20,  # Z6 — Anaerobic
    5.00,  # Z7 — Neuromuscular sentinel; arbitrary "high enough" cap
)


@dataclass(slots=True, frozen=True)
class DefaultZones:
    """Seven absolute-watts zone boundaries.

    All seven values are required by Wahoo's POST /v1/power_zones
    payload, so the dataclass mirrors that shape. Float rather than
    int because integer rounding at low FTP values is irrelevant to
    Wahoo — they accept both.
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


def default_zones_for(ftp: float) -> DefaultZones:
    """Derive the seven Wahoo-style upper-boundary watts from ``ftp``.

    ``ftp`` is the user's functional threshold power in watts. Returns
    a :class:`DefaultZones` with zones 1 through 7 rounded to the
    nearest watt — Wahoo's app rounds too, and integer-watt boundaries
    read cleaner in template sensors.
    """
    if ftp <= 0:
        raise ValueError(f"ftp must be positive, got {ftp}")
    values = tuple(round(ftp * factor) for factor in _WAHOO_FACTORS)
    return DefaultZones(*values)
