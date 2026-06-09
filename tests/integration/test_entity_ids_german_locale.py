"""Regression: entity_ids stay English-style even on a German HA install.

In 0.7.7 we shipped ``suggested_object_id`` on every sensor because a
German user reported ``sensor.hawahooligan_kritische_leistung`` instead
of the documented ``sensor.hawahooligan_critical_power``. HA derives
entity_ids from the slugified friendly name of the active locale —
without our pin a fresh German install would slugify "Kritische Leistung"
straight into the registry.

This test loads the integration with ``hass.config.language = "de"``
BEFORE setup and asserts the entity_id pins held.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from ._setup import registered_entity_ids, setup_entity_id_probe

# (translation_key, expected English-style entity_id slug suffix)
# Mix of translation_key==slug entries and divergent ones from
# ``_OBJECT_ID_OVERRIDES`` — the bug only ever affected divergent
# entries in non-English locales, but we assert both to catch the
# wider regression class.
EXPECTED_ENGLISH_SLUGS = (
    "critical_power",
    "ftp",
    "last_workout",
    "average_power",
    "average_speed",
    "normalized_power",
    "training_stress_score",
    "average_heart_rate",
    "average_cadence",
    "total_duration",
    "paused_duration",
    "distance",
    "ascent",
    "duration",
    "calories",
    "work",
    "lifetime_distance",
    "lifetime_workouts",
)

# Slugs that would only appear if our pin failed in the German locale.
# Kept narrow on purpose — these are the exact shapes the 0.7.7 bug
# surfaced. Add more here as new sensors get German translations that
# diverge from their English slug.
GERMAN_LEAK_SLUGS = (
    "kritische_leistung",
    "durchschnittliche_leistung",
    "normalisierte_leistung",
    "durchschnittsgeschwindigkeit",
    "trainingsbelastungspunkte",
    "durchschnittliche_herzfrequenz",
    "durchschnittliche_trittfrequenz",
    "gesamtdauer",
    "pausenzeit",
    "letzte_aktivitat",
    "letzte_aktivitat_",
)


async def test_entity_ids_stay_english_in_german_locale(hass: HomeAssistant) -> None:
    hass.config.language = "de"
    await setup_entity_id_probe(hass)

    registered = registered_entity_ids(hass)

    # The documented slugs must be present.
    missing = {
        f"sensor.hawahooligan_{slug}"
        for slug in EXPECTED_ENGLISH_SLUGS
        if f"sensor.hawahooligan_{slug}" not in registered
    }
    assert not missing, (
        f"German-locale install lost English entity_id slugs: {sorted(missing)}. "
        f"Registered: {sorted(registered)}"
    )

    # The 0.7.7 bug-shape slugs must NOT appear.
    leaked = {
        f"sensor.hawahooligan_{slug}"
        for slug in GERMAN_LEAK_SLUGS
        if f"sensor.hawahooligan_{slug}" in registered
    }
    assert not leaked, (
        f"German friendly names leaked into entity_ids — suggested_object_id "
        f"pin is not holding: {sorted(leaked)}. Registered: {sorted(registered)}"
    )
