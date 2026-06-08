"""Constants for the HAWahooligan integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "hawahooligan"

PLATFORMS: Final = (Platform.SENSOR,)

# Wahoo Cloud API
API_BASE: Final = "https://api.wahooligan.com"
OAUTH2_AUTHORIZE: Final = f"{API_BASE}/oauth/authorize"
OAUTH2_TOKEN: Final = f"{API_BASE}/oauth/token"

# Least-privilege scopes for Phase 1-3. `power_zones_read` is added later when
# Phase 4 (FTP / critical-power sensor) lands. `offline_data` is documented for
# webhook use but kept here as a safety net for long-lived refresh-token flows.
SCOPES: Final = "user_read workouts_read offline_data"

# Coordinator poll interval. With the conditional single-workout fetch the
# integration uses ~1 call per poll → ~96/day, which fits comfortably inside
# the Wahoo Sandbox rate limit (250/day).
UPDATE_INTERVAL: Final = timedelta(minutes=15)

# Where we drop generated artifacts (GeoJSON tracks + the Leaflet viewer):
# ``<config>/www/hawahooligan/``. HA serves ``<config>/www/`` under
# ``/local/``, so the public URLs become ``/local/hawahooligan/<file>``.
WWW_SUBPATH: Final[tuple[str, ...]] = ("www", "hawahooligan")
WWW_URL_PREFIX: Final = "/local/hawahooligan"

# Workout-type table from the Wahoo Cloud API "Data Types" section. The
# `location` value is the source of truth for indoor/outdoor classification —
# robuster than a handpicked ID set when Wahoo extends the table.
WORKOUT_TYPES: Final[dict[int, tuple[str, str]]] = {
    0: ("BIKING", "OUTDOOR"),
    1: ("RUNNING", "OUTDOOR"),
    2: ("FE", "INDOOR"),
    3: ("RUNNING_TRACK", "OUTDOOR"),
    4: ("RUNNING_TRAIL", "OUTDOOR"),
    5: ("RUNNING_TREADMILL", "INDOOR"),
    6: ("WALKING", "OUTDOOR"),
    7: ("WALKING_SPEED", "OUTDOOR"),
    8: ("WALKING_NORDIC", "OUTDOOR"),
    9: ("HIKING", "OUTDOOR"),
    10: ("MOUNTAINEERING", "OUTDOOR"),
    11: ("BIKING_CYCLECROSS", "OUTDOOR"),
    12: ("BIKING_INDOOR", "INDOOR"),
    13: ("BIKING_MOUNTAIN", "OUTDOOR"),
    14: ("BIKING_RECUMBENT", "OUTDOOR"),
    15: ("BIKING_ROAD", "OUTDOOR"),
    16: ("BIKING_TRACK", "OUTDOOR"),
    17: ("BIKING_MOTOCYCLING", "OUTDOOR"),
    18: ("FE_GENERAL", "INDOOR"),
    19: ("FE_TREADMILL", "INDOOR"),
    20: ("FE_ELLIPTICAL", "INDOOR"),
    21: ("FE_BIKE", "INDOOR"),
    22: ("FE_ROWER", "INDOOR"),
    23: ("FE_CLIMBER", "INDOOR"),
    25: ("SWIMMING_LAP", "INDOOR"),
    26: ("SWIMMING_OPEN_WATER", "OUTDOOR"),
    27: ("SNOWBOARDING", "OUTDOOR"),
    28: ("SKIING", "OUTDOOR"),
    29: ("SKIING_DOWNHILL", "OUTDOOR"),
    30: ("SKIINGCROSS_COUNTRY", "OUTDOOR"),
    31: ("SKATING", "OUTDOOR"),
    32: ("SKATING_ICE", "INDOOR"),
    33: ("SKATING_INLINE", "INDOOR"),
    34: ("LONG_BOARDING", "OUTDOOR"),
    35: ("SAILING", "OUTDOOR"),
    36: ("WINDSURFING", "OUTDOOR"),
    37: ("CANOEING", "OUTDOOR"),
    38: ("KAYAKING", "OUTDOOR"),
    39: ("ROWING", "OUTDOOR"),
    40: ("KITEBOARDING", "OUTDOOR"),
    41: ("STAND_UP_PADDLE_BOARD", "OUTDOOR"),
    42: ("WORKOUT", "INDOOR"),
    43: ("CARDIO_CLASS", "INDOOR"),
    44: ("STAIR_CLIMBER", "INDOOR"),
    45: ("WHEELCHAIR", "OUTDOOR"),
    46: ("GOLFING", "OUTDOOR"),
    47: ("OTHER", "OUTDOOR"),
    49: ("BIKING_INDOOR_CYCLING_CLASS", "INDOOR"),
    56: ("WALKING_TREADMILL", "INDOOR"),
    61: ("BIKING_INDOOR_TRAINER", "INDOOR"),
    62: ("MULTISPORT", "OUTDOOR"),
    63: ("TRANSITION", "OUTDOOR"),
    64: ("EBIKING", "OUTDOOR"),
    65: ("TICKR_OFFLINE", "OUTDOOR"),
    66: ("YOGA", "INDOOR"),
    67: ("RUNNING_RACE", "OUTDOOR"),
    68: ("BIKING_INDOOR_VIRTUAL", "INDOOR"),
    69: ("MENTAL_STRENGTH", "INDOOR"),
    70: ("HANDCYCLING", "OUTDOOR"),
    71: ("RUNNING_INDOOR_VIRTUAL", "INDOOR"),
    255: ("UNKNOWN", "UNKNOWN"),
}


def workout_type_name(type_id: int | None) -> str | None:
    """Return the canonical Wahoo workout-type name, or ``None`` if unknown."""
    if type_id is None:
        return None
    entry = WORKOUT_TYPES.get(type_id)
    return entry[0] if entry else None


def is_indoor(type_id: int | None) -> bool:
    """Whether a workout-type id is classified as indoor by Wahoo.

    Falls back to ``False`` for unknown ids — outdoor is the safer default
    because the FIT parser handles "no GPS track found" gracefully, while
    skipping the parse on a falsely-flagged indoor workout would lose data.
    """
    if type_id is None:
        return False
    entry = WORKOUT_TYPES.get(type_id)
    return entry is not None and entry[1] == "INDOOR"
