# ─────────────────────────────────────────────────────────────────────────────
# Authentication against the IVolatility REST API.
#
# Two modes are supported:
#
#   1. Token mode — call ``GET /token/get`` with username+password, cache the
#      returned bearer token, and send it as the ``token`` query parameter.
#      Tokens expire after 30 minutes; the client refreshes automatically.
#   2. Credential mode — send ``username`` and ``password`` directly on every
#      request (supported by the upstream but less clean).
#
# The auth object is passed into :class:`~volpulse_core.clients.ivolatility.client.IVolatilityClient`
# and is responsible for signing every outgoing request.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import httpx

from volpulse_core.clients.ivolatility.config import IVolatilitySettings
from volpulse_core.clients.ivolatility.exceptions import IVolatilityAuthError

TOKEN_ENDPOINT = "/token/get"
TOKEN_TTL_SECONDS = 30 * 60  # documented subscription TTL
REFRESH_BUFFER_SECONDS = 60  # refresh a minute before expiry


@dataclass
class IVolatilityAuth:
    """Authentication state for the IVolatility client."""

    settings: IVolatilitySettings
    _client: httpx.AsyncClient = field(repr=False)
    _token: str | None = field(default=None, init=False, repr=False)
    _expires_at: dt.datetime | None = field(default=None, init=False, repr=False)

    @property
    def is_authenticated(self) -> bool:
        """True when we currently hold a valid token or credentials."""
        if self._token is not None and self._expires_at is not None:
            return dt.datetime.now(dt.UTC) < self._expires_at
        return bool(self.settings.username and self.settings.password)

    async def get_token(self) -> str:
        """Obtain (or refresh) a bearer token from ``/token/get``.

        Raises:
            IVolatilityAuthError: credentials are missing or the upstream
                rejected the authentication request.
        """
        now = dt.datetime.now(dt.UTC)
        if (
            self._token is not None
            and self._expires_at is not None
            and now < self._expires_at
        ):
            return self._token

        if not self.settings.username or not self.settings.password:
            raise IVolatilityAuthError(
                "IVOL_USERNAME and IVOL_PASSWORD are required to obtain a token"
            )

        try:
            resp = await self._client.get(
                TOKEN_ENDPOINT,
                params={
                    "username": self.settings.username,
                    "password": self.settings.password,
                },
                timeout=self.settings.timeout_seconds,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise IVolatilityAuthError(
                f"token request failed: {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise IVolatilityAuthError(f"token request failed: {exc}") from exc

        token = resp.text.strip()
        if not token:
            raise IVolatilityAuthError("token response was empty")

        self._token = token
        self._expires_at = now + dt.timedelta(seconds=TOKEN_TTL_SECONDS)
        return self._token

    def auth_params(self) -> dict[str, str | None]:
        """Return the authentication query parameters for a request.

        Token mode takes precedence; otherwise username+password are sent.
        """
        token = self._token
        if token is not None:
            return {"token": token, "username": None, "password": None}
        return {
            "token": None,
            "username": self.settings.username,
            "password": self.settings.password,
        }
