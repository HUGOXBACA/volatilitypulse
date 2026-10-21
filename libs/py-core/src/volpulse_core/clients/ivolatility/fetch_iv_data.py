"""Fetch historical option chains from the IVolatility API.

The upstream is metered and answers wide queries asynchronously:

* every request is paced by :class:`RateLimiter` (the subscription allows
  roughly one call per second),
* a wide window returns a job whose details URL is polled until the upstream
  publishes a download URL,
* the download itself is paginated, and every page is validated and
  checkpointed to Parquet before the next one is requested.

The ``from`` parameter is a Python keyword, so any upstream parameter named
``from`` is rewritten to ``from_`` before it is sent and mapped back when
the response is read.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from volpulse_core.clients.ivolatility.pagination import Page, iter_pages, poll_for_download
from volpulse_core.clients.ivolatility.rate_limit import RateLimiter
from volpulse_core.config import Settings, load_settings

__all__ = ["HistoricalFetcher", "main"]

#: Endpoint that accepts a chain query.
CHAIN_ENDPOINT = "/v1/option/chains"

#: Endpoint that accepts a historical query.
HISTORY_ENDPOINT = "/v1/option/history"

#: Key in the details payload that holds the download URL.
DOWNLOAD_KEY = "urlForDownloads"

#: Maximum number of records the upstream returns in a single page.
PAGE_SIZE = 500


@dataclass(frozen=True, slots=True)
class HistoricalFetcher:
    """Fetches historical chains from the IVolatility API."""

    settings: Settings
    output_dir: Path

    def __post_init__(self) -> None:
        """Create the output directory."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def limiter(self) -> RateLimiter:
        """The rate limiter shared by every upstream call."""
        return RateLimiter(
            self.settings.ivol_rate_limit_rps,
            max_concurrency=self.settings.ivol_max_concurrency,
        )

    async def _get_json(
        self, client: httpx.AsyncClient, url: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Perform one paced GET request and decode the JSON body.

        Args:
            client: The HTTP client.
            url: Absolute or relative URL.
            params: Query parameters.

        Returns:
            The decoded JSON body.

        Raises:
            httpx.HTTPStatusError: The upstream returned an error status.
        """
        limiter = self.limiter
        async with limiter.slot():
            response = await client.get(
                url, params=params, timeout=self.settings.ivol_timeout_seconds
            )
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, dict) else {"records": payload}

    async def fetch_window(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        start: date,
        end: date,
    ) -> list[Mapping[str, Any]]:
        """Fetch every record of a historical window.

        Args:
            client: The HTTP client.
            symbol: Underlying symbol.
            start: Inclusive start of the window.
            end: Exclusive end of the window.

        Returns:
            The records, in upstream order.
        """
        params = {
            "symbol": symbol,
            # `from` is a Python keyword: the upstream parameter is renamed.
            "from_": start.isoformat(),
            "to": end.isoformat(),
            "pageSize": PAGE_SIZE,
        }
        payload = await self._get_json(client, HISTORY_ENDPOINT, params)

        details_url = payload.get("urlForDetails")
        if details_url:
            download_url = await poll_for_download(
                lambda url: self._get_json(client, url, {}),
                details_url,
                download_key=DOWNLOAD_KEY,
            )
            payload = await self._get_json(client, download_url, {})

        records: list[Mapping[str, Any]] = []
        page_number = 0

        async def fetch_page(index: int) -> Page:
            page_payload = await self._get_json(
                client,
                HISTORY_ENDPOINT,
                {**params, "page": index},
            )
            page_records = page_payload.get("records") or []
            has_more = bool(page_payload.get("hasMore"))
            return Page(records=tuple(page_records), next_page=index + 1 if has_more else None)

        async for page_records in iter_pages(fetch_page):
            records.extend(page_records)
            page_number += 1
            self._checkpoint(symbol, start, end, page_number, records)

        return records

    def _checkpoint(
        self,
        symbol: str,
        start: date,
        end: date,
        page_number: int,
        records: list[Mapping[str, Any]],
    ) -> Path:
        """Persist the records fetched so far, so a crash can resume.

        Args:
            symbol: Underlying symbol.
            start: Start of the window.
            end: End of the window.
            page_number: Number of pages fetched so far.
            records: The records fetched so far.

        Returns:
            The path of the checkpoint file.
        """
        path = self.output_dir / f"{symbol}_{start}_{end}_page{page_number}.parquet"
        frame = pl.DataFrame(records) if records else pl.DataFrame()
        frame.write_parquet(path, compression="zstd")
        return path


async def _run(settings: Settings, output_dir: Path, symbols: list[str], days: int) -> int:
    """Fetch the requested windows and write them to the output directory."""
    end = datetime.now(UTC).date()
    start = end - timedelta(days=days)

    fetcher = HistoricalFetcher(settings=settings, output_dir=output_dir)
    headers = {"x-api-key": settings.ivol_api_key}

    async with httpx.AsyncClient(
        base_url=settings.ivol_base_url,
        headers=headers,
    ) as client:
        for symbol in symbols:
            records = await fetcher.fetch_window(client, symbol, start, end)
            frame = pl.DataFrame(records) if records else pl.DataFrame()
            target = output_dir / f"{symbol}_{start}_{end}.parquet"
            frame.write_parquet(target, compression="zstd")
            print(f"fetched {len(records)} records for {symbol} -> {target}", flush=True)

    return 0


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Command line arguments. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(
        prog="fetch-iv-data",
        description="Fetch historical option chains from IVolatility.",
    )
    parser.add_argument("--symbols", required=True, help="Comma separated underlying symbols.")
    parser.add_argument("--days", type=int, default=30, help="Length of the window in days.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("var/artifacts/ivolatility"),
        help="Directory the Parquet artefacts are written to.",
    )
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except RuntimeError as error:
        print(f"fetch-iv-data: {error}", file=sys.stderr)
        return 2

    symbols = [symbol.strip() for symbol in args.symbols.split(",") if symbol.strip()]
    if not symbols:
        print("fetch-iv-data: no symbols requested", file=sys.stderr)
        return 2

    return asyncio.run(_run(settings, args.output_dir, symbols, args.days))


if __name__ == "__main__":
    raise SystemExit(main())
