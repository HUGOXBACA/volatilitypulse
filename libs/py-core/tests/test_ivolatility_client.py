"""Tests for the IVolatility REST client.

Uses unittest.mock to patch httpx.AsyncClient.request so no network is
required. Example payloads are taken from the IVolatility OpenAPI spec.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import polars as pl
import pytest

from volpulse_core.clients.ivolatility import (
    APIResponse,
    Endpoints,
    IVolatilityAPIError,
    IVolatilityAuthError,
    IVolatilityClient,
    IVolatilitySettings,
    equity_stock_prices,
)


def _json_envelope(data: Any, code: str = "DONE", details_url: str | None = None) -> str:
    import json

    status: dict[str, Any] = {
        "executionTime": 10,
        "recordsFound": len(data) if isinstance(data, list) else 1,
        "code": code,
    }
    if details_url is not None:
        status["urlForDetails"] = details_url
    if code == "DONE" and details_url is None:
        status["urlForDownloads"] = None
    return json.dumps({"status": status, "query": {}, "data": data})


def _pending_envelope(details_url: str) -> str:
    import json

    return json.dumps(
        {
            "status": {
                "executionTime": 10,
                "recordsFound": 0,
                "code": "PENDING",
                "urlForDetails": details_url,
            },
            "query": {},
            "data": [],
        }
    )


def make_client() -> IVolatilityClient:
    settings = IVolatilitySettings(
        base_url="https://api.ivolatility.com",
        username="user",
        password="pass",
        rate_limit_rps=1000.0,
    )
    return IVolatilityClient(settings)


# ── auth ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auth_gets_token() -> None:
    async def handler(method: str, url: str, **kwargs: Any) -> httpx.Response:
        params = kwargs.get("params", {})
        assert params.get("username") == "user"
        assert params.get("password") == "pass"
        return httpx.Response(200, text="abc123token", request=httpx.Request(method, url))

    client = make_client()
    with patch.object(client._client, "request", new_callable=AsyncMock) as mock:
        mock.side_effect = handler
        token = await client.get_token()
    await client.aclose()
    assert token == "abc123token"


@pytest.mark.asyncio
async def test_auth_missing_credentials() -> None:
    settings = IVolatilitySettings(base_url="https://api.ivolatility.com")
    client = IVolatilityClient(settings)
    try:
        with pytest.raises(IVolatilityAuthError):
            await client.get_token()
    finally:
        await client.aclose()


# ── fetch ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_returns_dataframe() -> None:
    payload = _json_envelope(
        [
            {"symbol": "AAPL", "date": "2024-01-16", "close": 172.26},
            {"symbol": "AAPL", "date": "2024-01-17", "close": 173.1},
        ]
    )

    async def handler(method: str, url: str, **kwargs: Any) -> httpx.Response:
        params = kwargs.get("params", {})
        assert params.get("symbol") == "AAPL"
        assert params.get("from") == "2024-01-01"
        return httpx.Response(
            200, text=payload, headers={"content-type": "application/json"},
            request=httpx.Request(method, url),
        )

    client = make_client()
    with patch.object(client._client, "request", new_callable=AsyncMock) as mock:
        mock.side_effect = handler
        df = await equity_stock_prices(
            client, symbol="AAPL", from_="2024-01-01", to="2024-01-31"
        )
    await client.aclose()
    assert isinstance(df, pl.DataFrame)
    assert df.shape == (2, 3)
    assert df["symbol"].to_list() == ["AAPL", "AAPL"]


@pytest.mark.asyncio
async def test_fetch_pending_then_download() -> None:
    details_url = "https://api.ivolatility.com/results/details/abc"
    download_url = "https://api.ivolatility.com/results/download/xyz"
    payload = _json_envelope(
        [{"symbol": "AAPL", "date": "2024-01-16", "close": 172.26}]
    )

    call_count = [0]

    async def handler(method: str, url: str, **kwargs: Any) -> httpx.Response:
        if "token/get" in url:
            return httpx.Response(200, text="tok", request=httpx.Request(method, url))
        if "details" in url:
            if call_count[0] == 0:
                call_count[0] += 1
                return httpx.Response(200, text=_pending_envelope(details_url), request=httpx.Request(method, url))
            return httpx.Response(
                200,
                text=_json_envelope({"urlForDownloads": download_url}, code="DONE"),
                request=httpx.Request(method, url),
            )
        if "download" in url:
            return httpx.Response(200, text=payload, headers={"content-type": "text/csv"}, request=httpx.Request(method, url))
        # Stock prices request
        return httpx.Response(200, text=payload, headers={"content-type": "application/json"}, request=httpx.Request(method, url))

    client = make_client()
    with patch.object(client._client, "request", new_callable=AsyncMock) as mock:
        mock.side_effect = handler
        df = await equity_stock_prices(
            client, symbol="AAPL", from_="2024-01-01", to="2024-01-31"
        )
    await client.aclose()
    assert df.shape == (1, 3)


@pytest.mark.asyncio
async def test_fetch_api_error() -> None:
    async def handler(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(400, text='{"error":"bad symbol"}', request=httpx.Request(method, url))

    client = make_client()
    with patch.object(client._client, "request", new_callable=AsyncMock) as mock:
        mock.side_effect = handler
        with pytest.raises(IVolatilityAPIError):
            await equity_stock_prices(client, symbol="BAD", from_="2024-01-01")
    await client.aclose()


# ── fetch_json ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_json_returns_envelope() -> None:
    payload = _json_envelope([{"symbol": "AAPL"}])

    async def handler(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200, text=payload, headers={"content-type": "application/json"},
            request=httpx.Request(method, url),
        )

    client = make_client()
    with patch.object(client._client, "request", new_callable=AsyncMock) as mock:
        mock.side_effect = handler
        env = await client.fetch_json(Endpoints.EQUITY_STOCK_PRICES, params={"symbol": "AAPL"})
    await client.aclose()
    assert isinstance(env, APIResponse)
    assert env.status.code == "DONE"
    assert env.status.recordsFound == 1


# ── endpoints export ────────────────────────────────────────────────────────

def test_endpoints_are_typed() -> None:
    assert Endpoints.EQUITY_STOCK_PRICES.path == "/equities/eod/stock-prices"
    assert Endpoints.EQUITY_STOCK_PRICES.method == "GET"
    assert "symbol" in Endpoints.EQUITY_STOCK_PRICES.params
