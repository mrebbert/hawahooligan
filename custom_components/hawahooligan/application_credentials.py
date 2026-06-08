"""Application Credentials platform for HAWahooligan.

Returns the Wahoo Cloud authorization server so the HA OAuth2 framework can
drive the auth-code flow on behalf of the user-provided client_id/secret.
"""

from __future__ import annotations

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return the Wahoo Cloud OAuth2 authorization server."""
    return AuthorizationServer(
        authorize_url=OAUTH2_AUTHORIZE,
        token_url=OAUTH2_TOKEN,
    )
