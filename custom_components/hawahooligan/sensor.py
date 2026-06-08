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
    PERCENTAGE,  # noqa: F401 — reserved for Phase-4 zone-share sensors
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
from .coordinator import WahooCoordinator, WorkoutData


@dataclass(frozen=True, kw_only=True)
class WahooSensorDescription(SensorEntityDescription):
    """Describe a Wahoo summary sensor and how to project ``WorkoutData`` onto it."""

    value_fn: Callable[[WorkoutData], float | int | str | datetime | None]


SUMMARY_SENSORS: tuple[WahooSensorDescription, ...] = (
    WahooSensorDescription(
        key="distance",
        translation_key="distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.distance_km,
    ),
    WahooSensorDescription(
        key="ascent",
        translation_key="ascent",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.ascent_m,
    ),
    WahooSensorDescription(
        key="duration",
        translation_key="duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.duration_min,
    ),
    WahooSensorDescription(
        key="speed_avg",
        translation_key="speed_avg",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.speed_avg_kmh,
    ),
    WahooSensorDescription(
        key="power_avg",
        translation_key="power_avg",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.power_avg_w,
    ),
    WahooSensorDescription(
        key="power_np",
        translation_key="power_np",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.power_np_w,
    ),
    WahooSensorDescription(
        key="tss",
        translation_key="tss",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.tss,
    ),
    WahooSensorDescription(
        key="heart_rate_avg",
        translation_key="heart_rate_avg",
        # No device_class for HR — HA has none. Custom unit + measurement class.
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.heart_rate_avg_bpm,
    ),
    WahooSensorDescription(
        key="cadence_avg",
        translation_key="cadence_avg",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.cadence_avg_rpm,
    ),
    WahooSensorDescription(
        key="calories",
        translation_key="calories",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.calories_kcal,
    ),
    WahooSensorDescription(
        key="work",
        translation_key="work",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_JOULE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.work_kj,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HawahooliganConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensor entities for the workout summary + the headline timestamp."""
    coordinator = entry.runtime_data.coordinator
    entities: list[CoordinatorEntity[WahooCoordinator]] = [
        WahooLastWorkoutSensor(coordinator, entry.entry_id)
    ]
    entities.extend(
        WahooSummarySensor(coordinator, entry.entry_id, description)
        for description in SUMMARY_SENSORS
    )
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
        self._attr_device_info = _device_info(entry_id)

    @property
    def native_value(self) -> float | int | str | datetime | None:
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)
