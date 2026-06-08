"""Pytest configuration for Tier-1 unit tests.

These tests target pure helper modules (no Home Assistant runtime). We load
each helper directly via ``importlib`` and expose it as a top-level module
(``fit``, ``totals``) so tests can ``from fit import …`` /
``from totals import …`` without dragging
``custom_components/hawahooligan/__init__.py`` (and its HA dependencies)
into the import graph.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "hawahooligan"


def _load(name: str, path: Path) -> None:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)


_load("fit", _ROOT / "fit.py")
_load("totals", _ROOT / "totals.py")
