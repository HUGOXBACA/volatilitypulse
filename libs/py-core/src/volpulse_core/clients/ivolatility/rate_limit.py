"""Pacing for the IVolatility upstream API.

The subscription is metered (roughly one request per second), so every call
to the upstream must be paced. This module implements that pacing once, in
one place, so that no caller can accidentally burst.

Two variants are provided:

* :meth:`RateLimiter.slot` — an async context manager for ``asyncio`` code.
* :meth:`RateLimiter.sync_slot` — a blocking context manager for scripts.

Both enforce two independent limits:

* a **rate**: calls are spaced by at least ``1 / rate_per_second`` seconds;
* a **concurrency**: at most ``max_concurrency`` calls are in flight.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator

__all__ = ["RateLimiter"]


class RateLimiter:
    """Pace calls to a rate-limited upstream API.

    Args:
        rate_per_second: Maximum sustained call rate. Must be positive.
            For the IVolatility subscription this is ``1.0``.
        max_concurrency: Maximum number of calls in flight at once.
    """

    __slots__ = (
        "_interval",
        "_max_concurrency",
        "_async_lock",
        "_thread_lock",
        "_semaphore",
        "_next_slot",
        "_acquired",
        "_wait_seconds",
        "_peak_inflight",
        "_inflight",
    )

    def __init__(self, rate_per_second: float, *, max_concurrency: int = 1) -> None:
        if rate_per_second <= 0.0:
            raise ValueError(f"rate_per_second must be positive, got {rate_per_second}")
        if max_concurrency < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {max_concurrency}")

        self._interval = 1.0 / rate_per_second
        self._max_concurrency = max_concurrency
        self._async_lock = asyncio.Lock()
        self._thread_lock = threading.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._next_slot = 0.0
        self._acquired = 0
        self._wait_seconds = 0.0
        self._peak_inflight = 0
        self._inflight = 0

    # ── Introspection ──────────────────────────────────────────────────────

    @property
    def interval(self) -> float:
        """Minimum spacing between two calls, in seconds."""
        return self._interval

    @property
    def acquired(self) -> int:
        """Total number of calls that were paced through this limiter."""
        return self._acquired

    @property
    def total_wait_seconds(self) -> float:
        """Total time spent blocked waiting for a slot."""
        return self._wait_seconds

    @property
    def peak_inflight(self) -> int:
        """Highest observed number of simultaneous calls."""
        return self._peak_inflight

    @property
    def current_delay(self) -> float:
        """Seconds the next caller would have to wait right now."""
        return max(0.0, self._next_slot - time.monotonic())

    # ── Async usage ────────────────────────────────────────────────────────

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Acquire a paced slot for the duration of the ``async with`` block.

        Raises:
            asyncio.CancelledError: Propagated unchanged; the slot is
                released so a cancelled call never leaks concurrency.
        """
        await self._semaphore.acquire()
        try:
            waited = await self._wait_for_slot()
            self._acquired += 1
            self._wait_seconds += waited
            self._inflight += 1
            self._peak_inflight = max(self._peak_inflight, self._inflight)
            try:
                yield
            finally:
                self._inflight -= 1
        finally:
            self._semaphore.release()

    async def _wait_for_slot(self) -> float:
        """Block until the next call may start. Returns the time waited."""
        waited = 0.0
        async with self._async_lock:
            now = time.monotonic()
            delay = self._next_slot - now
            if delay > 0.0:
                await asyncio.sleep(delay)
                waited = delay
            self._next_slot = time.monotonic() + self._interval
        return waited

    # ── Blocking usage ─────────────────────────────────────────────────────

    @contextmanager
    def sync_slot(self) -> Iterator[None]:
        """Acquire a paced slot for the duration of the ``with`` block."""
        with self._thread_lock:
            now = time.monotonic()
            delay = self._next_slot - now
            if delay > 0.0:
                time.sleep(delay)
                self._wait_seconds += delay
            self._next_slot = time.monotonic() + self._interval
            self._acquired += 1
        yield

    # ── Introspection helpers for metrics ──────────────────────────────────

    def snapshot(self) -> dict[str, float]:
        """Return a flat snapshot suitable for exporting as metrics."""
        return {
            "volpulse_ratelimit_acquired_total": float(self._acquired),
            "volpulse_ratelimit_wait_seconds_total": self._wait_seconds,
            "volpulse_ratelimit_peak_inflight": float(self._peak_inflight),
            "volpulse_ratelimit_current_delay_seconds": self.current_delay,
        }
