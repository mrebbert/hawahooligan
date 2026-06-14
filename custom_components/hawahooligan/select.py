"""Workout picker as a Home Assistant ``SelectEntity``.

Surfaces every workout in the coordinator's in-memory index as a
dropdown so users can pin the headline sensors + map to any ride —
indoor or outdoor, with or without a GPS track — without leaving HA's
own UI. Replaces the in-iframe Leaflet picker that 0.7.10 still shipped.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HawahooliganConfigEntry
from .const import DOMAIN
from .coordinator import WahooCoordinator

# Always-present sentinel option that releases the pin and follows the
# newest workout again. Sorted to the top of the dropdown.
_LATEST_OPTION = "⏵ Latest workout"


def _icon_for(workout: Mapping[str, Any]) -> str:
    """Pick a one-glyph hint for the workout's nature.

    Indoor / virtual rides get the trainer glyph; manual entries get
    the pencil; everything else falls back to the bike. We deliberately
    don't try to encode every Wahoo workout type — just enough so the
    user can scan the dropdown.
    """
    if workout.get("indoor"):
        return "🏠"
    if workout.get("manual"):
        return "📝"
    return "🚴"


def _format_starts(starts: str | None) -> str:
    if not starts:
        return "????-??-??"
    try:
        dt = datetime.fromisoformat(starts.replace("Z", "+00:00"))
    except ValueError:
        return starts[:10]
    return dt.strftime("%Y-%m-%d")


def _format_duration(duration_min: Any) -> str | None:
    """Compact ``H:MM`` for >= 1 h, else ``MM min``. ``None`` if unknown."""
    if not isinstance(duration_min, (int, float)) or duration_min <= 0:
        return None
    total_minutes = int(round(float(duration_min)))
    if total_minutes < 60:
        return f"{total_minutes} min"
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}:{minutes:02d} h"


def _build_label(workout: Mapping[str, Any]) -> str:
    """Stable, locale-agnostic dropdown label.

    ``"2026-06-10 · Morning ride · 1:15 h · 🚴"`` — ISO date keeps lexical
    sort aligned with chronological sort and lets users type-search by
    year or month. Duration appears between name and icon when known so
    the user can pick by ride length without opening anything else; the
    trailing icon is the indoor / manual / outdoor cue.
    """
    when = _format_starts(workout.get("starts"))
    name = (workout.get("name") or workout.get("workout_type") or "Workout").strip()
    icon = _icon_for(workout)
    duration = _format_duration(workout.get("duration_min"))
    if duration:
        return f"{when} · {name} · {duration} · {icon}"
    return f"{when} · {name} · {icon}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HawahooliganConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register the single workout-picker select for this config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([WahooWorkoutPickerSelect(coordinator, entry.entry_id)])


def _device_info(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        manufacturer="Wahoo Fitness",
        name="HAWahooligan",
        entry_type=DeviceEntryType.SERVICE,
    )


class WahooWorkoutPickerSelect(CoordinatorEntity[WahooCoordinator], SelectEntity):
    """Dropdown over every workout in the coordinator's index.

    Options refresh whenever the coordinator pushes an update —
    ``_refresh_manifest`` calls ``async_update_listeners`` after every
    write so a fresh backfill makes the dropdown grow live.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "workout_picker"

    def __init__(self, coordinator: WahooCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_workout_picker"
        self._attr_device_info = _device_info(entry_id)
        # Reverse-map rebuilt every time ``options`` is read so
        # ``async_select_option`` can resolve label → workout_id without
        # parsing the displayed string.
        self._option_to_id: dict[str, int | None] = {}

    @property
    def suggested_object_id(self) -> str | None:
        return "workout_picker"

    @property
    def available(self) -> bool:
        # Picker reads from the local manifest mirror — API failures don't matter.
        return True

    @property
    def options(self) -> list[str]:
        self._option_to_id = {_LATEST_OPTION: None}
        labels = [_LATEST_OPTION]
        for workout in self.coordinator.known_workouts():
            workout_id = workout.get("id")
            if not isinstance(workout_id, int):
                continue
            label = _build_label(workout)
            # Two workouts at the same minute with the same name would
            # collide — suffix the id to keep options unique.
            if label in self._option_to_id:
                label = f"{label} #{workout_id}"
            self._option_to_id[label] = workout_id
            labels.append(label)
        return labels

    @property
    def current_option(self) -> str | None:
        selected_id = self.coordinator.selected_workout_id
        if selected_id is None:
            return _LATEST_OPTION
        workout = self.coordinator.known_workout(selected_id)
        if workout is None:
            # Selected an id that's not (yet) in the index — surface the
            # raw id so the user can still see what's pinned.
            return f"#{selected_id}"
        # Make sure the reverse-map is current — properties can be read in
        # any order.
        if not self._option_to_id:
            self.options  # noqa: B018 — triggers map rebuild as a side-effect
        return _build_label(workout)

    async def async_select_option(self, option: str) -> None:
        # ``options`` may not have been polled yet — rebuild the map
        # before we lose context.
        if option not in self._option_to_id:
            self.options  # noqa: B018 — rebuilds ``_option_to_id``
        workout_id = self._option_to_id.get(option)
        await self.coordinator.async_select_workout(workout_id)
