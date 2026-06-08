"""Pytest configuration for Tier-1 unit tests.

These tests target pure helper modules (no Home Assistant runtime). We load
``fit.py`` directly via ``importlib`` and expose it as the top-level module
``fit`` so tests can ``from fit import …`` without dragging
``custom_components/hawahooligan/__init__.py`` (and its HA dependencies) into
the import graph.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_FIT_PATH = Path(__file__).resolve().parent.parent / "custom_components" / "hawahooligan" / "fit.py"

_spec = importlib.util.spec_from_file_location("fit", _FIT_PATH)
assert _spec and _spec.loader
_fit = importlib.util.module_from_spec(_spec)
sys.modules["fit"] = _fit
_spec.loader.exec_module(_fit)
