"""Tests for the upstream pagination helpers."""

from __future__ import annotations

from typing import Any

import pytest

from volpulse_core.clients.ivolatility.pagination import Page, iter_pages, poll_for_download


@pytest.mark.asyncio
async def test_poll_returns_as_soon_as_the_job_is_ready() -> None:
    """The download URL must be returned without unnecessary waiting."""
    payloads = [
        {"status": "pending"},
        {"status": "pending"},
        {"urlForDownloads": "https://example.invalid/download/42"},
    ]
    calls: list[str] = []

    async def fetch(url: str) -> dict[str, Any]:
        calls.append(url)
        return payloads[len(calls) - 1]

    async def sleep(_seconds: float) -> None:
        return None

    url = await poll_for_download(
        fetch,
        "https://example.invalid/details/7",
        poll_interval=0.01,
        timeout=5.0,
        sleep=sleep,
    )

    assert url == "https://example.invalid/download/42"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_poll_times_out_when_the_job_never_completes() -> None:
    """A job that never becomes ready must fail loudly."""
    clock = {"now": 0.0}

    async def fetch(_url: str) -> dict[str, Any]:
        return {"status": "pending"}

    async def sleep(seconds: float) -> None:
        clock["now"] += seconds

    def monotonic() -> float:
        return clock["now"]

    with pytest.raises(TimeoutError):
        await poll_for_download(
            fetch,
            "https://example.invalid/details/7",
            poll_interval=1.0,
            timeout=3.0,
            monotonic=monotonic,
            sleep=sleep,
        )


@pytest.mark.asyncio
async def test_iter_pages_walks_every_page() -> None:
    """Every page must be yielded exactly once, in order."""
    pages = {
        0: Page(records=({"id": 0},), next_page=1),
        1: Page(records=({"id": 1},), next_page=2),
        2: Page(records=({"id": 2},), next_page=None),
    }
    requested: list[int] = []

    async def fetch(index: int) -> Page:
        requested.append(index)
        return pages[index]

    collected: list[tuple[Any, ...]] = []
    async for records in iter_pages(fetch):
        collected.extend(records)

    assert requested == [0, 1, 2]
    assert [record["id"] for record in collected] == [0, 1, 2]


@pytest.mark.asyncio
async def test_iter_pages_respects_max_pages() -> None:
    """The page cap must stop the walk."""
    async def fetch(index: int) -> Page:
        return Page(records=({"id": index},), next_page=index + 1)

    collected: list[tuple[Any, ...]] = []
    async for records in iter_pages(fetch, max_pages=2):
        collected.extend(records)

    assert len(collected) == 2


@pytest.mark.asyncio
async def test_iter_pages_handles_an_empty_first_page() -> None:
    """An empty page with a cursor must not end the walk."""
    pages = {
        0: Page(records=(), next_page=1),
        1: Page(records=({"id": 1},), next_page=None),
    }

    async def fetch(index: int) -> Page:
        return pages[index]

    collected: list[tuple[Any, ...]] = []
    async for records in iter_pages(fetch):
        collected.extend(records)

    assert [record["id"] for record in collected] == [1]
