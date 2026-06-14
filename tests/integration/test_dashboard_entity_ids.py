"""Regression: every entity_id referenced by the example dashboard exists.

HA generates entity_ids from the *translated friendly name* (slugified) for
the active HA locale, not from the ``translation_key``. Two ways this can
drift away from the documented YAML:

* Someone renames a sensor in ``strings.json`` / ``translations/en.json``
  and forgets to update ``dashboard/dashboard.yaml``.
* A non-English locale registers a sensor we haven't pinned with
  ``suggested_object_id`` — see :mod:`test_entity_ids_german_locale`.

This file covers the English-locale case. The German-locale case is its
own test so the assertion shape can be tighter.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant

from ._setup import registered_entity_ids, setup_entity_id_probe

_DASHBOARD = Path(__file__).resolve().parent.parent.parent / "dashboard" / "dashboard.yaml"
_ENTITY_ID_RE = re.compile(r"sensor\.hawahooligan_[a-z0-9_]+")

# Suffixes belonging to user-configured ``utility_meter`` helpers (see the
# README's bulk-path YAML block). The dashboard references them but the
# integration doesn't register them — out of scope for this regression.
_UTILITY_METER_CYCLES = ("_daily", "_weekly", "_monthly", "_yearly")


def _entity_ids_referenced_by_dashboard() -> set[str]:
    text = _DASHBOARD.read_text(encoding="utf-8")
    return {eid for eid in _ENTITY_ID_RE.findall(text) if not eid.endswith(_UTILITY_METER_CYCLES)}


async def test_dashboard_entity_ids_exist(hass: HomeAssistant) -> None:
    await setup_entity_id_probe(hass)

    referenced = _entity_ids_referenced_by_dashboard()
    assert referenced, "dashboard.yaml does not reference any HAWahooligan sensor"

    registered = registered_entity_ids(hass)
    missing = referenced - registered
    assert not missing, (
        f"dashboard.yaml references entity_ids that HA does not register: "
        f"{sorted(missing)}. Registered: {sorted(registered)}"
    )


async def test_dashboard_yaml_parses(hass: HomeAssistant) -> None:
    """Sanity check: the YAML still parses (the regex test wouldn't catch syntax errors)."""
    parsed = yaml.safe_load(_DASHBOARD.read_text(encoding="utf-8"))
    assert parsed["views"], "dashboard.yaml has no views"
