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

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Auto-enable HA's discovery of ``custom_components/`` for every test.

    Without this fixture HA refuses to load the integration during tests
    (it only loads built-in components by default).
    """
    yield
