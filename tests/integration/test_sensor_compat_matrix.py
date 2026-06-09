"""Regression: every Wahoo sensor's (device_class, state_class) is HA-compatible.

HA's recorder validates ``device_class`` / ``state_class`` pairs at
runtime via ``homeassistant.components.sensor.const.DEVICE_CLASS_STATE_CLASSES``
and emits a noisy warning when a sensor declares an incompatible combo
(e.g. ``device_class=ENERGY`` + ``state_class=MEASUREMENT`` — energy
expects accumulating ``total`` / ``total_increasing``). The original
``work_kj`` sensor tripped this in 0.7.x. This test pins the matrix so
the bug class can't reappear silently.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.components.sensor.const import DEVICE_CLASS_STATE_CLASSES

from custom_components.hawahooligan.sensor import (
    LIFETIME_SENSORS,
    SUMMARY_SENSORS,
    WahooCriticalPowerSensor,
    WahooFtpSensor,
    WahooLastWorkoutSensor,
)


def _device_class_value(value) -> str | None:
    """Normalize enum / string device_class to a plain string key."""
    if value is None:
        return None
    if isinstance(value, SensorDeviceClass):
        return value.value
    return str(value)


def _state_class_value(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, SensorStateClass):
        return value.value
    return str(value)


def _check_compatible(label: str, device_class, state_class) -> None:
    """Assert the (dc, sc) pair is in HA's compatibility matrix.

    Unset device_class means anything goes — HA only validates when a
    device_class is declared.
    """
    if device_class is None or state_class is None:
        return
    dc = _device_class_value(device_class)
    sc = _state_class_value(state_class)
    allowed = DEVICE_CLASS_STATE_CLASSES.get(dc, set())
    allowed_values = {s.value if hasattr(s, "value") else s for s in allowed}
    assert sc in allowed_values, (
        f"{label}: device_class={dc!r} forbids state_class={sc!r}. "
        f"HA accepts {sorted(allowed_values)!r}. This combo would emit "
        f"a recorder warning at runtime."
    )


def test_summary_sensor_descriptions_have_compatible_classes() -> None:
    for desc in SUMMARY_SENSORS:
        _check_compatible(f"SUMMARY_SENSORS[{desc.key}]", desc.device_class, desc.state_class)


def test_lifetime_sensor_descriptions_have_compatible_classes() -> None:
    for desc in LIFETIME_SENSORS:
        _check_compatible(f"LIFETIME_SENSORS[{desc.key}]", desc.device_class, desc.state_class)


def test_standalone_sensor_classes_have_compatible_classes() -> None:
    """The three sensors that aren't description-driven still get checked.

    ``getattr(cls, "_attr_device_class")`` resolves the property descriptor
    that ``SensorEntity`` defines on the base class — to find the actual
    value the subclass declared, walk MRO ``__dict__`` and pick the first
    own-class definition.
    """

    def _own_attr(cls: type, name: str):
        for ancestor in cls.__mro__:
            if name in ancestor.__dict__:
                value = ancestor.__dict__[name]
                if not isinstance(value, property):
                    return value
        return None

    for cls in (WahooFtpSensor, WahooCriticalPowerSensor, WahooLastWorkoutSensor):
        device_class = _own_attr(cls, "_attr_device_class")
        state_class = _own_attr(cls, "_attr_state_class")
        _check_compatible(cls.__name__, device_class, state_class)
