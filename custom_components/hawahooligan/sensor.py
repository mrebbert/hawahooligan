"""Sensor entities for the most recent Wahoo workout."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HawahooliganConfigEntry
from .const import DOMAIN
from .coordinator import WahooCoordinator, WahooPowerZonesCoordinator, WorkoutData
from .power_zones import PowerZonesData
from .totals import LifetimeTotals


@dataclass(frozen=True, kw_only=True)
class WahooSensorDescription(SensorEntityDescription):
    """Describe a Wahoo summary sensor and how to project ``WorkoutData`` onto it.

    ``suggested_object_id`` pins the entity_id suffix so the slug stays
    stable across locales — HA otherwise derives it from the user-locale's
    translated friendly name, which produces things like
    ``sensor.hawahooligan_kritische_leistung`` on a German install.
    """

    value_fn: Callable[[WorkoutData], float | int | str | datetime | None]
    suggested_object_id: str


# ``suggested_object_id`` per entry matches the slugified ENGLISH friendly
# name that ``en.json`` produces — so a German install that bypassed our
# default by registering when ``de.json`` was already loaded still ends up
# with ``sensor.hawahooligan_average_speed`` rather than
# ``…_durchschnittsgeschwindigkeit``. Existing entries in the registry are
# never auto-renamed; this only fixes new installs going forward.
SUMMARY_SENSORS: tuple[WahooSensorDescription, ...] = (
    WahooSensorDescription(
        key="distance",
        translation_key="distance",
        suggested_object_id="distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.distance_km,
    ),
    WahooSensorDescription(
        key="ascent",
        translation_key="ascent",
        suggested_object_id="ascent",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.ascent_m,
    ),
    WahooSensorDescription(
        key="duration",
        translation_key="duration",
        suggested_object_id="duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.duration_min,
    ),
    WahooSensorDescription(
        key="duration_total",
        translation_key="duration_total",
        suggested_object_id="total_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.duration_total_min,
    ),
    WahooSensorDescription(
        key="duration_paused",
        translation_key="duration_paused",
        suggested_object_id="paused_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.duration_paused_min,
    ),
    WahooSensorDescription(
        key="speed_avg",
        translation_key="speed_avg",
        suggested_object_id="average_speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.speed_avg_kmh,
    ),
    WahooSensorDescription(
        key="power_avg",
        translation_key="power_avg",
        suggested_object_id="average_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.power_avg_w,
    ),
    WahooSensorDescription(
        key="power_np",
        translation_key="power_np",
        suggested_object_id="normalized_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.power_np_w,
    ),
    WahooSensorDescription(
        key="tss",
        translation_key="tss",
        suggested_object_id="training_stress_score",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.tss,
    ),
    WahooSensorDescription(
        key="heart_rate_avg",
        translation_key="heart_rate_avg",
        suggested_object_id="average_heart_rate",
        # No device_class for HR — HA has none. Custom unit + measurement class.
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.heart_rate_avg_bpm,
    ),
    WahooSensorDescription(
        key="cadence_avg",
        translation_key="cadence_avg",
        suggested_object_id="average_cadence",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.cadence_avg_rpm,
    ),
    WahooSensorDescription(
        key="calories",
        translation_key="calories",
        suggested_object_id="calories",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.calories_kcal,
    ),
    WahooSensorDescription(
        key="work",
        translation_key="work",
        suggested_object_id="work",
        # No device_class=ENERGY here: HA's ENERGY class expects accumulating
        # state_class (``total`` / ``total_increasing``), but ``work_kj`` is a
        # per-workout snapshot that resets to a fresh value with every ride.
        # Keeping the unit makes it readable; declaring it as energy would
        # mis-feed the long-term-statistics pipeline.
        native_unit_of_measurement=UnitOfEnergy.KILO_JOULE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.work_kj,
    ),
)


@dataclass(frozen=True, kw_only=True)
class WahooLifetimeSensorDescription(SensorEntityDescription):
    """Describe a lifetime-total sensor and how to project ``LifetimeTotals``.

    ``field_name`` is the sum() field the sensor projects (e.g. ``distance_km``)
    and drives the outdoor/indoor split attributes. The workout-count sensor
    passes ``None`` because its split goes through count-based helpers instead.
    ``suggested_object_id`` keeps the entity_id stable across locales — same
    rationale as on :class:`WahooSensorDescription`.
    """

    value_fn: Callable[[LifetimeTotals], float | int]
    suggested_object_id: str
    field_name: str | None = None


# Lifetime totals — ``state_class=total_increasing`` makes the HA recorder
# treat these as monotonically growing meters. Users can drop a utility_meter
# helper on top to get week / month / year buckets without any extra Python.
# Each sensor also exposes ``outdoor`` / ``indoor`` sub-sums as attributes so
# templates and automations can split the totals by location.
LIFETIME_SENSORS: tuple[WahooLifetimeSensorDescription, ...] = (
    WahooLifetimeSensorDescription(
        key="lifetime_distance",
        translation_key="lifetime_distance",
        suggested_object_id="lifetime_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda t: t.distance_km,
        field_name="distance_km",
    ),
    WahooLifetimeSensorDescription(
        key="lifetime_ascent",
        translation_key="lifetime_ascent",
        suggested_object_id="lifetime_ascent",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda t: t.ascent_m,
        field_name="ascent_m",
    ),
    WahooLifetimeSensorDescription(
        key="lifetime_duration",
        translation_key="lifetime_duration",
        suggested_object_id="lifetime_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda t: t.duration_min,
        field_name="duration_min",
    ),
    WahooLifetimeSensorDescription(
        key="lifetime_calories",
        translation_key="lifetime_calories",
        suggested_object_id="lifetime_calories",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda t: t.calories_kcal,
        field_name="calories_kcal",
    ),
    WahooLifetimeSensorDescription(
        key="lifetime_work",
        translation_key="lifetime_work",
        suggested_object_id="lifetime_work",
        native_unit_of_measurement=UnitOfEnergy.KILO_JOULE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda t: t.work_kj,
        field_name="work_kj",
    ),
    WahooLifetimeSensorDescription(
        key="lifetime_tss",
        translation_key="lifetime_tss",
        suggested_object_id="lifetime_tss",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda t: t.tss,
        field_name="tss",
    ),
    WahooLifetimeSensorDescription(
        key="lifetime_workouts",
        translation_key="lifetime_workouts",
        suggested_object_id="lifetime_workouts",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda t: t.workout_count,
        field_name=None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HawahooliganConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensor entities for the workout summary + the headline timestamp."""
    coordinator = entry.runtime_data.coordinator
    power_zones_coordinator = entry.runtime_data.power_zones_coordinator
    entities: list[CoordinatorEntity[Any]] = [WahooLastWorkoutSensor(coordinator, entry.entry_id)]
    entities.extend(
        WahooSummarySensor(coordinator, entry.entry_id, description)
        for description in SUMMARY_SENSORS
    )
    entities.extend(
        WahooLifetimeSensor(coordinator, entry.entry_id, description)
        for description in LIFETIME_SENSORS
    )
    entities.append(WahooFtpSensor(power_zones_coordinator, entry.entry_id))
    entities.append(WahooCriticalPowerSensor(power_zones_coordinator, entry.entry_id))
    async_add_entities(entities)


def _device_info(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        manufacturer="Wahoo Fitness",
        name="HAWahooligan",
        entry_type=DeviceEntryType.SERVICE,
    )


class WahooLastWorkoutSensor(CoordinatorEntity[WahooCoordinator], SensorEntity):
    """Headline sensor: state = start time of the most recent workout."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_workout"
    _attr_suggested_object_id = "last_workout"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: WahooCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_last_workout"
        self._attr_device_info = _device_info(entry_id)

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data
        if data is None or not data.starts:
            return None
        try:
            # Wahoo returns ISO 8601 strings with a trailing ``Z``.
            return datetime.fromisoformat(data.starts.replace("Z", "+00:00"))
        except ValueError:
            return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        data = self.coordinator.data
        if data is None:
            return None
        return {
            "workout_id": data.workout_id,
            "name": data.name,
            "workout_type_id": data.workout_type_id,
            "workout_type": data.workout_type_name,
            "indoor": data.indoor,
            "manual": data.manual,
            "edited": data.edited,
            "time_zone": data.time_zone,
            "fitness_app_id": data.fitness_app_id,
            "starts": data.starts,
            "geojson_url": data.geojson_url,
            "route_id": data.route_id,
            "plan_id": data.plan_id,
            "plan_ids": data.plan_ids,
            "recent": [
                {
                    "id": r.id,
                    "name": r.name,
                    "starts": r.starts,
                    "workout_type": r.workout_type_name,
                    "indoor": r.indoor,
                    "manual": r.manual,
                    "has_track": r.has_track,
                }
                for r in data.recent
            ],
        }


class WahooSummarySensor(CoordinatorEntity[WahooCoordinator], SensorEntity):
    """Sensor backed by a single field of ``WorkoutData``."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WahooCoordinator,
        entry_id: str,
        description: WahooSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_suggested_object_id = description.suggested_object_id
        self._attr_device_info = _device_info(entry_id)

    @property
    def native_value(self) -> float | int | str | datetime | None:
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)


class WahooLifetimeSensor(CoordinatorEntity[WahooCoordinator], SensorEntity):
    """Sensor backed by ``WahooCoordinator.totals`` (a :class:`LifetimeTotals`).

    Each sensor exposes the headline total as its state and the indoor /
    outdoor sub-sums as attributes — so templates can build location-aware
    automations without spawning a second set of entities.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WahooCoordinator,
        entry_id: str,
        description: WahooLifetimeSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_suggested_object_id = description.suggested_object_id
        self._attr_device_info = _device_info(entry_id)

    @property
    def native_value(self) -> float | int:
        return self.entity_description.value_fn(self.coordinator.totals)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        totals: LifetimeTotals = self.coordinator.totals
        description = self.entity_description
        # Workout-count sensor — split by counting entries tagged indoor /
        # outdoor. Pre-split data carries no tag and stays out of both
        # sub-counts.
        if description.field_name is None:
            return {
                "outdoor": totals.workout_count_outdoor,
                "indoor": totals.workout_count_indoor,
            }
        return {
            "outdoor": totals.sum(description.field_name, indoor=False),
            "indoor": totals.sum(description.field_name, indoor=True),
        }


class WahooFtpSensor(CoordinatorEntity[WahooPowerZonesCoordinator], SensorEntity):
    """FTP (functional threshold power). Zone thresholds ride along as attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "ftp"
    _attr_suggested_object_id = "ftp"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: WahooPowerZonesCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_ftp"
        self._attr_device_info = _device_info(entry_id)

    @property
    def native_value(self) -> float | None:
        data: PowerZonesData | None = self.coordinator.data
        if data is None:
            return None
        return data.ftp

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        data: PowerZonesData | None = self.coordinator.data
        if data is None:
            return None
        return {
            "zone_count": data.zone_count,
            "zone_1": data.zone_1,
            "zone_2": data.zone_2,
            "zone_3": data.zone_3,
            "zone_4": data.zone_4,
            "zone_5": data.zone_5,
            "zone_6": data.zone_6,
            "zone_7": data.zone_7,
            "workout_type_id": data.workout_type_id,
            "workout_type_family_id": data.workout_type_family_id,
            "updated_at": data.updated_at,
        }


class WahooCriticalPowerSensor(CoordinatorEntity[WahooPowerZonesCoordinator], SensorEntity):
    """Critical power (MMP). Wahoo treats this as a separate metric from FTP."""

    _attr_has_entity_name = True
    _attr_translation_key = "critical_power"
    _attr_suggested_object_id = "critical_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: WahooPowerZonesCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_critical_power"
        self._attr_device_info = _device_info(entry_id)

    @property
    def native_value(self) -> float | None:
        data: PowerZonesData | None = self.coordinator.data
        if data is None:
            return None
        return data.critical_power
