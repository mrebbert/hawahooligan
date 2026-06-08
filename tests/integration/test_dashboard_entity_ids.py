"""Regression: every entity_id referenced by the example dashboard exists.

HA generates entity_ids from the *translated English name* (slugified), not
from the ``translation_key``. So if someone renames a sensor in
``strings.json`` / ``translations/en.json`` without updating
``dashboard/dashboard.yaml``, the dashboard quietly stops finding the
sensors. This test catches that drift by loading the integration into a
real HA stack, dumping the registered ``sensor.hawahooligan_*`` entity_ids,
and asserting every id in ``dashboard.yaml`` lands.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

_DASHBOARD = Path(__file__).resolve().parent.parent.parent / "dashboard" / "dashboard.yaml"
_ENTITY_ID_RE = re.compile(r"sensor\.hawahooligan_[a-z0-9_]+")


def _entity_ids_referenced_by_dashboard() -> set[str]:
    text = _DASHBOARD.read_text(encoding="utf-8")
    return set(_ENTITY_ID_RE.findall(text))


async def _setup_integration(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="dashboard-entity-id-probe",
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.hawahooligan.config_entry_oauth2_flow.async_get_config_entry_implementation",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.hawahooligan.config_entry_oauth2_flow.OAuth2Session",
            return_value=MagicMock(),
        ),
        patch("custom_components.hawahooligan.WahooApi", return_value=MagicMock()),
        patch(
            "custom_components.hawahooligan.WahooCoordinator.async_config_entry_first_refresh",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.hawahooligan.WahooCoordinator._async_update_data",
            new=AsyncMock(return_value=WorkoutData(workout_id=1)),
        ),
        patch(
            "custom_components.hawahooligan.WahooCoordinator.async_backfill_recent",
            new=AsyncMock(return_value=0),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _registered_entity_ids(hass: HomeAssistant) -> set[str]:
    registry = er.async_get(hass)
    return {
        ent.entity_id
        for ent in registry.entities.values()
        if ent.platform == DOMAIN and ent.entity_id.startswith("sensor.hawahooligan_")
    }


async def test_dashboard_entity_ids_exist(hass: HomeAssistant) -> None:
    await _setup_integration(hass)

    referenced = _entity_ids_referenced_by_dashboard()
    assert referenced, "dashboard.yaml does not reference any HAWahooligan sensor"

    registered = _registered_entity_ids(hass)
    missing = referenced - registered
    assert not missing, (
        f"dashboard.yaml references entity_ids that HA does not register: "
        f"{sorted(missing)}. Registered: {sorted(registered)}"
    )


async def test_dashboard_yaml_parses(hass: HomeAssistant) -> None:
    """Sanity check: the YAML still parses (the regex test wouldn't catch syntax errors)."""
    parsed = yaml.safe_load(_DASHBOARD.read_text(encoding="utf-8"))
    assert parsed["views"], "dashboard.yaml has no views"
