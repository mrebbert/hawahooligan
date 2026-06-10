"""Pytest configuration for Tier-2 integration tests.

These tests run against a real Home Assistant instance via
``pytest-homeassistant-custom-component`` and will exercise the integration's
config flow, coordinator, sensors and services end-to-end with a mocked Wahoo
Cloud API.

Install the heavier dependency group first::

    .venv/bin/pip install -e ".[test-integration]"

Then run only the integration tests::

    .venv/bin/pytest tests/integration -v
"""

from __future__ import annotations

import shutil
from collections.abc import Generator
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

from custom_components.hawahooligan.const import WWW_SUBPATH


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Auto-enable HA's discovery of ``custom_components/`` for every test.

    Without this fixture HA refuses to load the integration during tests
    (it only loads built-in components by default).
    """
    yield


@pytest.fixture(autouse=True)
def reset_geojson_dir(hass: HomeAssistant) -> Generator[None]:
    """Wipe ``<testing_config>/www/hawahooligan/`` before each test.

    ``pytest-homeassistant-custom-component`` reuses the same
    ``testing_config`` directory across tests, so a leftover
    ``workouts.json`` or stray ``<id>.geojson`` from one test can
    contaminate the next. The accumulator manifest makes this
    especially noisy — clean it eagerly.
    """
    target = Path(hass.config.path(*WWW_SUBPATH))
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    yield
