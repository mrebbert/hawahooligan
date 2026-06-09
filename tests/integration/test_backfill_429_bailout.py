"""Regression: ``async_backfill_recent`` bails after 3 consecutive 429s.

Background: 0.7.5 fixed an effectively-infinite retry loop when Wahoo's
larger (hourly / daily) rate-limit window was exhausted. The original
backfill kept calling the detail endpoint until the listing was
exhausted, burning log noise and the user's token slot without making
progress. The bail-out counter caps retry at 3 consecutive 429s; this
test pins the contract so a future refactor can't quietly drop or
raise it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hawahooligan.api import WahooApiError
from custom_components.hawahooligan.const import DOMAIN
from custom_components.hawahooligan.coordinator import WorkoutData

from ._setup import oauth_implementation_patches


async def test_backfill_bails_after_three_consecutive_429s(hass: HomeAssistant) -> None:
    """The detail endpoint is called exactly 3 times before bail-out.

    Setup wires a 5-workout listing so the loop has plenty of room to
    keep going if it ignored the strike count.
    """
    mock_api = MagicMock()
    # Listing succeeds — the bug is in the per-detail loop, not the listing.
    mock_api.async_get_workouts = AsyncMock(
        return_value={"workouts": [{"id": i} for i in range(1, 6)]}
    )
    # Every detail call goes 429. Real Wahoo behavior when the daily quota
    # is exhausted — the rolling 5-min budget already cleared.
    mock_api.async_get_workout = AsyncMock(
        side_effect=WahooApiError("rate limited", status_code=429)
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HAWahooligan",
        data={"auth_implementation": "x", "token": {"access_token": "fake"}},
        unique_id="backfill-429-probe",
    )
    entry.add_to_hass(hass)

    with (
        oauth_implementation_patches(),
        patch("custom_components.hawahooligan.WahooApi", return_value=mock_api),
        # First refresh stays a no-op so we don't count its listing call.
        patch(
            "custom_components.hawahooligan.WahooCoordinator._async_update_data",
            new=AsyncMock(return_value=WorkoutData(workout_id=None)),
        ),
        # Power-zones first refresh is irrelevant — make it a no-op so we
        # don't trip the reauth path on accident.
        patch(
            "custom_components.hawahooligan.WahooPowerZonesCoordinator.async_config_entry_first_refresh",
            new=AsyncMock(),
        ),
        # Geojson files never exist in the test fixture — force the loop to
        # actually invoke the detail endpoint rather than short-circuit.
        patch(
            "custom_components.hawahooligan.coordinator._has_geojson",
            return_value=False,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        # ``async_block_till_done`` waits for the background backfill task
        # spawned by ``async_setup_entry`` to complete.
        await hass.async_block_till_done()

    # Exactly 3 detail calls = strike count met, loop broke. If the
    # bail-out is ever removed or its threshold widened, this lands above
    # 3 (or hits the listing length, 5).
    assert mock_api.async_get_workout.call_count == 3, (
        f"expected exactly 3 detail calls before bail-out, got "
        f"{mock_api.async_get_workout.call_count}"
    )
