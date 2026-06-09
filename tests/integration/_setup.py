"""Shared helpers for entity_id probe tests.

Both ``test_dashboard_entity_ids`` and ``test_entity_ids_german_locale``
load the config entry into a real HA instance with mocked Wahoo internals,
then walk the entity registry. The patch stack is identical — only the
HA locale differs — so the setup lives here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData


async def setup_entity_id_probe(hass: HomeAssistant) -> None:
    """Install the integration with everything but entity registration mocked out."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="entity-id-probe",
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


def registered_entity_ids(hass: HomeAssistant) -> set[str]:
    """Return all ``sensor.hawahooligan_*`` entity_ids currently in the registry."""
    registry = er.async_get(hass)
    return {
        ent.entity_id
        for ent in registry.entities.values()
        if ent.platform == DOMAIN and ent.entity_id.startswith("sensor.hawahooligan_")
    }
