# ─────────────────────────────────────────────────────────────────────────────
# IVolatility REST client.
#
# A single, reusable async client that:
#
#   * authenticates via ``/token/get`` (username/password or bearer token),
#   * paces every call through the shared :class:`RateLimiter` so the
#     subscription quota (~1 req/s) is never exceeded,
#   * retries transient failures with exponential backoff,
#   * handles the asynchronous job flow (``PENDING`` → poll ``urlForDetails``
#     → download from ``urlForDownloads``),
#   * rewrites the reserved Python keyword ``from`` to ``from_`` on the wire.
#
# Example:
#
#     async with IVolatilityClient(settings) as client:
#         df = await client.fetch(Endpoints.EQUITY_STOCK_PRICES,
#                                 symbol="AAPL", from_="2024-01-01", to="2024-01-31")
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import io
from collections.abc import Mapping
from typing import Any, Self

import httpx
import polars as pl

from volpulse_core.clients.ivolatility.auth import IVolatilityAuth
from volpulse_core.clients.ivolatility.config import IVolatilitySettings
from volpulse_core.clients.ivolatility.endpoints import Endpoint
from volpulse_core.clients.ivolatility.exceptions import (
    IVolatilityAPIError,
    IVolatilityAuthError,
    IVolatilityRateLimitError,
)
from volpulse_core.clients.ivolatility.models import APIResponse
from volpulse_core.clients.ivolatility.pagination import poll_for_download
from volpulse_core.clients.ivolatility.rate_limit import RateLimiter

_PARAM_RENAMES = {"from_": "from"}


class IVolatilityClient:
    """Async client for the IVolatility REST API."""

    def __init__(
        self,
        settings: IVolatilitySettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or IVolatilitySettings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.settings.base_url,
            timeout=self.settings.timeout_seconds,
        )
        self._limiter = RateLimiter(
            self.settings.rate_limit_rps, max_concurrency=self.settings.max_concurrency
        )
        self._auth = IVolatilityAuth(self.settings, self._client)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_token(self) -> str:
        """Obtain (or refresh) a bearer token from ``/token/get``."""
        return await self._auth.get_token()

    # ── Public API ────────────────────────────────────────────────────────

    async def fetch(
        self,
        endpoint: Endpoint,
        *,
        params: Mapping[str, Any] | None = None,
        poll_interval: float = 2.0,
        poll_timeout: float = 300.0,
        raw: bool = False,
        **kwargs: Any,
    ) -> pl.DataFrame | str:
        """Fetch one endpoint and return the result.

        Args:
            endpoint: The endpoint definition from :mod:`endpoints`.
            params: Query parameters. ``from_`` is accepted and rewritten to
                ``from`` before sending.
            poll_interval: Seconds between ``urlForDetails`` polls.
            poll_timeout: Maximum seconds to wait for a PENDING job.
            raw: Return the raw response body (CSV/text) instead of a
                Polars DataFrame.
            **kwargs: Additional query parameters passed directly to the
                endpoint (e.g. ``symbol="AAPL"``). Merged with ``params``.

        Returns:
            A Polars DataFrame, or a raw string when ``raw=True``.

        Raises:
            IVolatilityAuthError, IVolatilityAPIError, IVolatilityRateLimitError,
            IVolatilityPendingError, httpx.RequestError.
        """
        merged_params = dict(params or {})
        merged_params.update(kwargs)
        request_params = self._build_params(endpoint, merged_params)
        response = await self._request_with_retries(
            endpoint.method, endpoint.path, request_params
        )
        body = await self._handle_response(response, poll_interval, poll_timeout, raw)
        return body

    async def fetch_json(
        self,
        endpoint: Endpoint,
        *,
        params: Mapping[str, Any] | None = None,
        poll_interval: float = 2.0,
        poll_timeout: float = 300.0,
        **kwargs: Any,
    ) -> APIResponse:
        """Fetch one endpoint and return the parsed JSON envelope."""
        merged_params = dict(params or {})
        merged_params.update(kwargs)
        request_params = self._build_params(endpoint, merged_params)
        response = await self._request_with_retries(
            endpoint.method, endpoint.path, request_params
        )
        data = response.json()
        return APIResponse.model_validate(data)

    # ── Internals ─────────────────────────────────────────────────────────

    def _build_params(
        self, endpoint: Endpoint, extra: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        params = self._auth.auth_params()
        if extra:
            for key, value in extra.items():
                # Skip None values but keep falsy ones (e.g. strike=0).
                if value is None:
                    continue
                params[_PARAM_RENAMES.get(key, key)] = value
        return params

    async def _request_with_retries(
        self, method: str, path: str, params: dict[str, Any]
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                async with self._limiter.slot():
                    resp = await self._client.request(method, path, params=params)
            except IVolatilityAuthError:
                # Token may have expired mid-flight; force refresh and retry once.
                self._auth._token = None
                self._auth._expires_at = None
                async with self._limiter.slot():
                    resp = await self._client.request(method, path, params=params)

            if resp.status_code == 401:
                # Force a token refresh and retry once.
                self._auth._token = None
                self._auth._expires_at = None
                async with self._limiter.slot():
                    resp = await self._client.request(method, path, params=params)

            if resp.status_code == 429:
                last_error = IVolatilityRateLimitError("upstream rate limit exceeded")
                await asyncio.sleep(self.settings.backoff_base_seconds * attempt)
                continue

            if 400 <= resp.status_code < 500:
                raise IVolatilityAPIError(
                    resp.status_code, resp.text[:200], str(resp.url)
                )
            if resp.status_code >= 500:
                last_error = IVolatilityAPIError(
                    resp.status_code, resp.text[:200], str(resp.url)
                )
                await asyncio.sleep(self.settings.backoff_base_seconds * attempt)
                continue

            return resp

        if isinstance(last_error, IVolatilityAPIError):
            raise last_error
        if last_error is not None:
            raise last_error
        raise IVolatilityAPIError(0, "request failed after retries", None)

    async def _handle_response(
        self,
        response: httpx.Response,
        poll_interval: float,
        poll_timeout: float,
        raw: bool,
    ) -> pl.DataFrame | str:
        # Some endpoints return plain text/CSV directly.
        content_type = response.headers.get("content-type", "")
        if raw or "text/csv" in content_type or "text/plain" in content_type:
            return response.text

        envelope = APIResponse.model_validate(response.json())

        if envelope.is_pending and envelope.details_url:
            # The upstream is processing the job asynchronously. Poll the
            # details URL until it publishes a download URL, then download.
            async def fetch_details(url: str) -> Mapping[str, Any]:
                async with self._limiter.slot():
                    resp = await self._client.get(url)
                resp.raise_for_status()
                return resp.json()  # type: ignore[no-any-return]

            download_url = await poll_for_download(
                fetch_details,
                envelope.details_url,
                poll_interval=poll_interval,
                max_wait_seconds=poll_timeout,
            )

            # Download the artefact through the limiter so it is paced too.
            async with self._limiter.slot():
                dl_resp = await self._client.get(download_url)
            dl_resp.raise_for_status()
            body = dl_resp.text
        else:
            body = None

        if raw:
            return response.text  # type: ignore[unreachable]

        return _parse_envelope_to_dataframe(envelope, body)


def _parse_envelope_to_dataframe(
    envelope: APIResponse, raw_body: str | None = None
) -> pl.DataFrame:
    """Convert an APIResponse envelope into a Polars DataFrame.

    The ``data`` field is either a list of objects or, for wide queries, a
    raw CSV string that was already downloaded to disk by the caller.
    """
    # A downloaded artefact body takes precedence over the envelope payload.
    if raw_body is not None:
        return pl.read_csv(io.StringIO(raw_body))

    if envelope.data is None:
        return pl.DataFrame()

    if isinstance(envelope.data, str):
        return pl.read_csv(io.StringIO(envelope.data))

    return pl.DataFrame(envelope.data)
