"""Regression: ``hawahooligan.full_backfill`` paginates + terminates + emits events.

Four contracts pinned:

1. Pagination walks until the listing returns an empty ``workouts`` list.
2. ``EVENT_BACKFILL_PROGRESS`` fires once per processed page (the final
   page carries ``done=True``).
3. Every workout in the returned pages ends up in
   ``coordinator.totals`` — guards against a future refactor that drops
   the detail fetch on the page-loop edge.
4. The picker manifest accumulates every page's workouts so the viewer
   dropdown grows beyond the regular 20-recent cap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import Event, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.const import (
    DOMAIN,
    EVENT_BACKFILL_PROGRESS,
    MANIFEST_FILENAME,
    WWW_SUBPATH,
)
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches


async def _setup_entry(hass: HomeAssistant, mock_api: MagicMock) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="full-backfill-probe",
    )
    entry.add_to_hass(hass)
    with (
        oauth_implementation_patches(),
        patch("custom_components.hawahooligan.WahooApi", return_value=mock_api),
        patch(
            "custom_components.hawahooligan.WahooCoordinator._async_update_data",
            new=AsyncMock(return_value=WorkoutData(workout_id=None)),
        ),
        patch(
            "custom_components.hawahooligan.WahooPowerZonesCoordinator.async_config_entry_first_refresh",
            new=AsyncMock(),
        ),
        # The first-setup backfill is unrelated to this test — silence it
        # so the listing/detail mock counts only reflect full_backfill.
        patch(
            "custom_components.hawahooligan.WahooCoordinator.async_backfill_recent",
            new=AsyncMock(return_value=0),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_full_backfill_paginates_until_empty_and_fires_events(
    hass: HomeAssistant,
) -> None:
    # Two pages of workouts, then the empty terminator. Each detail call
    # returns just enough to make ``_build_workout_data`` happy.
    page_listings = [
        {"workouts": [{"id": 1}, {"id": 2}]},
        {"workouts": [{"id": 3}]},
        {"workouts": []},
    ]
    detail_payloads = {
        1: {"id": 1, "workout_summary": {"distance": 10000}},
        2: {"id": 2, "workout_summary": {"distance": 20000}},
        3: {"id": 3, "workout_summary": {"distance": 5000}},
    }

    mock_api = MagicMock()
    mock_api.async_get_workouts = AsyncMock(side_effect=page_listings)
    mock_api.async_get_workout = AsyncMock(
        side_effect=lambda workout_id: detail_payloads[workout_id]
    )

    entry = await _setup_entry(hass, mock_api)
    coordinator = entry.runtime_data.coordinator

    # Listen for the progress event. HA's bus.async_listen returns a
    # remover function; we don't call it because the loop ends with the test.
    events: list[Event] = []

    def _capture(event: Event) -> None:
        events.append(event)

    hass.bus.async_listen(EVENT_BACKFILL_PROGRESS, _capture)

    await hass.services.async_call(
        DOMAIN,
        "full_backfill",
        {
            "config_entry_id": entry.entry_id,
            "with_tracks": False,
            # Keep the budget far above 4 calls so RateLimitBudget.acquire
            # never actually sleeps.
            "max_calls_per_window": 100,
            "window_seconds": 300,
            "max_pages": 50,
        },
        blocking=True,
    )
    # Service is fire-and-forget — wait for the background task to finish.
    # ``wait_background_tasks=True`` is load-bearing: HA's default
    # ``async_block_till_done`` only drains foreground work, so without
    # this the backfill task can still be mid-page when assertions fire.
    await hass.async_block_till_done(wait_background_tasks=True)

    # Three pages = three listing calls. Three workouts = three detail calls.
    assert mock_api.async_get_workouts.call_count == 3, (
        f"expected 3 listing calls (page 1, 2, terminator), got "
        f"{mock_api.async_get_workouts.call_count}"
    )
    assert mock_api.async_get_workout.call_count == 3

    # All three workouts in the totals — proves the detail loop wired up.
    assert coordinator.totals.workout_count == 3

    # Exactly one EVENT_BACKFILL_PROGRESS per listing call. The empty-page
    # event carries done=True; the intermediate ones carry done=False.
    # We sort by page number for the assertion because HA's bus dispatch
    # ordering for sync listeners isn't strictly guaranteed across pages
    # that fire in rapid succession.
    progress_events: list[dict[str, Any]] = sorted(
        (dict(e.data) for e in events), key=lambda e: e["page"]
    )
    assert len(progress_events) == 3
    assert [e["page"] for e in progress_events] == [1, 2, 3]
    assert progress_events[0]["done"] is False
    assert progress_events[1]["done"] is False
    assert progress_events[2]["done"] is True
    assert progress_events[2]["added"] == 3


async def test_full_backfill_grows_picker_manifest(hass: HomeAssistant) -> None:
    """Backfill writes every page's workouts into ``workouts.json``.

    Without the per-page manifest write, the dropdown stays capped at
    the 20 entries the regular poll's recent-listing endpoint returns —
    making ``full_backfill`` useless from the viewer's perspective.
    """
    page_listings = [
        {
            "workouts": [
                {"id": 101, "name": "Morning ride", "starts": "2026-06-01T07:00:00Z"},
                {"id": 102, "name": "Evening ride", "starts": "2026-06-01T18:00:00Z"},
            ]
        },
        {
            "workouts": [
                {"id": 103, "name": "Weekend long", "starts": "2026-06-08T09:00:00Z"},
            ]
        },
        {"workouts": []},
    ]
    detail_payloads = {
        wid: {"id": wid, "workout_summary": {"distance": 10000}} for wid in (101, 102, 103)
    }

    mock_api = MagicMock()
    mock_api.async_get_workouts = AsyncMock(side_effect=page_listings)
    mock_api.async_get_workout = AsyncMock(
        side_effect=lambda workout_id: detail_payloads[workout_id]
    )

    entry = await _setup_entry(hass, mock_api)

    await hass.services.async_call(
        DOMAIN,
        "full_backfill",
        {
            "config_entry_id": entry.entry_id,
            "with_tracks": False,
            "max_calls_per_window": 100,
            "window_seconds": 300,
            "max_pages": 50,
        },
        blocking=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    manifest_path = Path(hass.config.path(*WWW_SUBPATH)) / MANIFEST_FILENAME
    assert manifest_path.is_file(), "manifest never written"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    ids_in_manifest = {entry["id"] for entry in payload.get("workouts", [])}
    assert ids_in_manifest == {101, 102, 103}, (
        f"manifest only contains {sorted(ids_in_manifest)} — full_backfill "
        f"did not feed all pages into the picker"
    )
