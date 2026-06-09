"""Regression: ``WahooApi._request`` parses Retry-After + retries once.

Pins three contracts on the API client's defensive 429 net:

1. ``_parse_retry_after`` defaults to 300s on missing/garbage headers and
   clamps absurd values to 1800s.
2. ``_request`` sleeps for the parsed Retry-After then retries once on
   the first 429, surfacing the second 429 as
   ``WahooApiError(status_code=429)`` rather than looping forever.
3. ``_request`` returns the JSON body on a successful retry.

Tier-2 (HA imports) because ``api.py`` pulls in ``OAuth2Session`` and
``ConfigEntryAuthFailed`` at module load time. Mocks ``asyncio.sleep``
so the test isn't paced by the real 300-second default.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.hawahooligan.api import (
    WahooApi,
    WahooApiError,
    _parse_retry_after,
)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, 300),
        ("", 300),
        ("nonsense", 300),
        ("-5", 300),
        ("0", 300),
        ("1", 1),
        ("60", 60),
        ("300", 300),
        ("3600", 1800),  # clamped to _RETRY_AFTER_MAX_SECONDS
        ("9999999", 1800),
    ],
)
def test_parse_retry_after(header: str | None, expected: int) -> None:
    assert _parse_retry_after(header) == expected


def _mock_response(status: int, json_body=None, retry_after: str | None = None) -> MagicMock:
    """Build a MagicMock that quacks like an aiohttp.ClientResponse."""
    response = MagicMock()
    response.status = status
    response.headers = {"Retry-After": retry_after} if retry_after else {}
    response.json = AsyncMock(return_value=json_body if json_body is not None else {})
    response.text = AsyncMock(return_value="fake-error-body")
    return response


async def test_request_retries_once_on_429_then_returns_body(
    hass: HomeAssistant,
) -> None:
    """First call → 429 with Retry-After. Second call → 200 with JSON body."""
    first = _mock_response(429, retry_after="42")
    second = _mock_response(200, json_body={"workouts": [{"id": 1}]})

    session = MagicMock()
    session.async_request = AsyncMock(side_effect=[first, second])

    api = WahooApi(hass, session)

    with patch("custom_components.hawahooligan.api.asyncio.sleep", new=AsyncMock()) as sleep_spy:
        result = await api._request("GET", "/v1/workouts")

    assert result == {"workouts": [{"id": 1}]}
    assert session.async_request.call_count == 2
    sleep_spy.assert_awaited_once_with(42)


async def test_request_raises_after_two_consecutive_429s(hass: HomeAssistant) -> None:
    """Both attempts 429 → ``WahooApiError(status_code=429)``, no infinite loop."""
    first = _mock_response(429, retry_after="10")
    second = _mock_response(429, retry_after="10")

    session = MagicMock()
    session.async_request = AsyncMock(side_effect=[first, second])

    api = WahooApi(hass, session)

    with (
        patch("custom_components.hawahooligan.api.asyncio.sleep", new=AsyncMock()),
        pytest.raises(WahooApiError) as exc_info,
    ):
        await api._request("GET", "/v1/workouts")

    assert exc_info.value.status_code == 429
    assert session.async_request.call_count == 2
