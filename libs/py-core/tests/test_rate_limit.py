"""Tests for the upstream rate limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from volpulse_core.clients.ivolatility.rate_limit import RateLimiter


def test_rejects_invalid_configuration() -> None:
    """A limiter must refuse nonsensical configuration."""
    with pytest.raises(ValueError):
        RateLimiter(0.0)
    with pytest.raises(ValueError):
        RateLimiter(-1.0)
    with pytest.raises(ValueError):
        RateLimiter(1.0, max_concurrency=0)


def test_spacing_between_calls() -> None:
    """Calls must be spaced by at least the configured interval."""
    limiter = RateLimiter(50.0)  # 20 ms apart
    start = time.monotonic()

    for _ in range(4):
        with limiter.sync_slot():
            pass

    elapsed = time.monotonic() - start
    assert elapsed >= 0.06
    assert limiter.acquired == 4


def test_slot_releases_on_exception() -> None:
    """An exception inside the slot must not leak concurrency."""
    limiter = RateLimiter(1000.0)

    with pytest.raises(RuntimeError):
        with limiter.sync_slot():
            raise RuntimeError("boom")

    with limiter.sync_slot():
        pass

    assert limiter.acquired == 2


@pytest.mark.asyncio
async def test_async_slot_limits_concurrency() -> None:
    """No more than ``max_concurrency`` calls may be in flight."""
    limiter = RateLimiter(1000.0, max_concurrency=2)
    active = 0
    peak = 0

    async def worker() -> None:
        nonlocal active, peak
        async with limiter.slot():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(6)))

    assert peak <= 2
    assert limiter.acquired == 6
    assert limiter.peak_inflight <= 2


@pytest.mark.asyncio
async def test_async_slot_releases_on_exception() -> None:
    """A cancelled or failing call must not consume a slot forever."""
    limiter = RateLimiter(1000.0, max_concurrency=1)

    with pytest.raises(RuntimeError):
        async with limiter.slot():
            raise RuntimeError("boom")

    async with limiter.slot():
        pass

    assert limiter.acquired == 2


def test_snapshot_exposes_metrics() -> None:
    """The limiter must expose a flat metric snapshot."""
    limiter = RateLimiter(1000.0)
    with limiter.sync_slot():
        pass

    snapshot = limiter.snapshot()
    assert snapshot["volpulse_ratelimit_acquired_total"] == 1.0
    assert "volpulse_ratelimit_current_delay_seconds" in snapshot
