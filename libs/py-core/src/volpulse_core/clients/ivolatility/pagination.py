"""Asynchronous pagination and job polling for the IVolatility API.

The upstream API does not return large option chains directly. A request for
a wide historical window returns a *job*: a payload that points at a details
URL. The details URL is polled until the upstream exposes a download URL,
and only then is the actual data fetched.

Both flows are implemented here, without any network dependency, so that
they can be unit tested deterministically:

* :func:`poll_for_download` — wait for an asynchronous job to become
  downloadable, then return the download URL.
* :func:`iter_pages` — iterate the record pages of a large result set
  without blocking the event loop.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["Page", "iter_pages", "poll_for_download"]


@dataclass(frozen=True, slots=True)
class Page:
    """One page of records plus the cursor for the next page."""

    records: tuple[Mapping[str, Any], ...]
    next_page: int | None = None

    @property
    def is_last(self) -> bool:
        """True when there is no further page to fetch."""
        return self.next_page is None


#: Signature of the coroutine that fetches the details payload.
DetailsFetcher = Callable[[str], Awaitable[Mapping[str, Any]]]

#: Signature of the coroutine that fetches one page of records.
PageFetcher = Callable[[int], Awaitable[Page]]


async def poll_for_download(
    fetch_details: DetailsFetcher,
    details_url: str,
    *,
    download_key: str = "urlForDownloads",
    poll_interval: float = 1.0,
    max_wait_seconds: float = 300.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> str:
    """Poll a job details URL until the download URL is available.

    The upstream publishes the download URL inside the details payload only
    once the job has been prepared, so the details payload is re-read every
    ``poll_interval`` seconds until ``download_key`` appears in it.

    Args:
        fetch_details: Coroutine that fetches and decodes a details payload.
        details_url: URL of the job details endpoint.
        download_key: Key holding the download URL in the details payload.
        poll_interval: Seconds between two polls.
        max_wait_seconds: Maximum number of seconds to wait for the job.
        monotonic: Clock used for the timeout (injectable for tests).
        sleep: Awaitable sleep (injectable for tests).

    Returns:
        The URL the finished job can be downloaded from.

    Raises:
        TimeoutError: The job did not become ready within ``timeout``.
    """
    if poll_interval <= 0.0:
        raise ValueError(f"poll_interval must be positive, got {poll_interval}")
    if max_wait_seconds <= 0.0:
        raise ValueError(f"max_wait_seconds must be positive, got {max_wait_seconds}")

    deadline = monotonic() + max_wait_seconds

    while True:
        payload = await fetch_details(details_url)
        download_url = payload.get(download_key)
        if download_url:
            return str(download_url)

        if monotonic() >= deadline:
            raise TimeoutError(
                f"job {details_url!r} did not publish {download_key!r} "
                f"within {max_wait_seconds:.1f}s"
            )

        await sleep(poll_interval)


async def iter_pages(
    fetch_page: PageFetcher,
    *,
    max_pages: int | None = None,
) -> AsyncIterator[Sequence[Mapping[str, Any]]]:
    """Iterate the pages of a paginated result set.

    The upstream caps a single response at roughly 500 records; wider windows
    have to be walked page by page. Pages are yielded as they arrive so the
    caller can persist them incrementally instead of buffering the whole
    window in memory.

    Args:
        fetch_page: Coroutine that fetches the page with a given index.
        max_pages: Optional cap on the number of pages to fetch.

    Yields:
        The records of each page, in upstream order.
    """
    if max_pages is not None and max_pages < 1:
        raise ValueError(f"max_pages must be >= 1, got {max_pages}")

    index = 0
    fetched = 0
    while max_pages is None or fetched < max_pages:
        page = await fetch_page(index)
        if page.records:
            yield page.records
        fetched += 1

        if page.is_last:
            return
        if page.next_page is None:
            return
        index = page.next_page
