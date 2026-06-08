"""Pytest configuration for Tier-1 unit tests.

These tests target pure helper functions (no Home Assistant runtime). When
``custom_components/hawahooligan/fit.py`` lands in Phase 2, this conftest will
load it via importlib (same pattern as 1komma5-ha's ``helpers.py``) so tests
can import it without pulling in the integration's HA-dependent ``__init__``.
"""

from __future__ import annotations
