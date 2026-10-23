# ─────────────────────────────────────────────────────────────────────────────
# Option chain builder — aggregates quotes into chain snapshots.
#
# Consumes normalized OptionQuote messages (from WebSocket/Kafka) and produces
# OptionChainSnapshot objects grouped by (underlying_symbol, expiry_epoch_day).
# Maintains per-symbol ordering via sequence numbers for gap detection.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from volpulse_core.models.chain import OptionChainSnapshot
from volpulse_core.models.quote import OptionQuote

logger = logging.getLogger(__name__)

__all__ = [
    "ChainBuilder",
    "ChainBuilderConfig",
    "ChainSnapshotHandler",
    "run_chain_builder",
]


# ── Configuration ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ChainBuilderConfig:
    """Configuration for chain builder."""

    # Maximum time to wait before emitting a snapshot (seconds)
    snapshot_interval: float = 1.0
    # Maximum quotes to buffer before forced emission
    max_buffer_size: int = 10000
    # Maximum gap in sequence numbers before warning
    max_sequence_gap: int = 1000
    # Emit snapshot on every quote if True (for testing)
    emit_on_every_quote: bool = False


# ── Handler Protocol ──────────────────────────────────────────────────────────


class ChainSnapshotHandler(Protocol):
    """Protocol for handling completed chain snapshots."""

    async def __call__(self, snapshot: OptionChainSnapshot) -> None: ...


# ── Internal State ────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _ChainBuffer:
    """Buffer for a single (underlying, expiry) chain."""

    underlying_symbol: str
    expiry_epoch_day: int
    quotes: dict[int, OptionQuote] = field(default_factory=dict)  # keyed by sequence
    last_emitted_sequence: int = 0
    last_emit_time: float = 0.0
    gaps_detected: int = 0


@dataclass(slots=True)
class _BuilderState:
    """Mutable builder state."""

    buffers: dict[tuple[str, int], _ChainBuffer] = field(default_factory=dict)
    quotes_received: int = 0
    snapshots_emitted: int = 0
    gaps_detected: int = 0
    last_activity_time: float = 0.0


# ── Chain Builder ─────────────────────────────────────────────────────────────


class ChainBuilder:
    """Aggregates OptionQuote messages into OptionChainSnapshot objects.

    Groups quotes by (underlying_symbol, expiry_epoch_day) and emits snapshots
    at regular intervals or when buffer reaches max size. Tracks sequence numbers
    per partition for gap detection.
    """

    __slots__ = (
        "_config",
        "_emit_task",
        "_handler",
        "_queue",
        "_shutdown_event",
        "_state",
        "_tasks",
    )

    def __init__(
        self,
        config: ChainBuilderConfig,
        handler: ChainSnapshotHandler | None = None,
    ) -> None:
        self._config = config
        self._handler = handler or self._default_handler
        self._state = _BuilderState()
        self._queue: asyncio.Queue[OptionQuote] = asyncio.Queue(
            maxsize=config.max_buffer_size
        )
        self._tasks: list[asyncio.Task[Any]] = []
        self._shutdown_event = asyncio.Event()
        self._emit_task: asyncio.Task[Any] | None = None

    async def _default_handler(self, snapshot: OptionChainSnapshot) -> None:
        """Default handler logs the snapshot."""
        logger.info(
            "Emitted chain snapshot: %s event_time_ns=%d quotes=%d seq=%d",
            snapshot.underlying_symbol,
            snapshot.event_time_ns,
            len(snapshot.quotes),
            snapshot.sequence,
        )

    def _get_buffer(self, underlying: str, expiry_day: int) -> _ChainBuffer:
        """Get or create buffer for (underlying, expiry)."""
        key = (underlying, expiry_day)
        if key not in self._state.buffers:
            self._state.buffers[key] = _ChainBuffer(
                underlying_symbol=underlying,
                expiry_epoch_day=expiry_day,
            )
        return self._state.buffers[key]

    async def add_quote(self, quote: OptionQuote) -> None:
        """Add a quote to the appropriate buffer."""
        if self._shutdown_event.is_set():
            raise RuntimeError("Chain builder is shutting down")

        try:
            self._queue.put_nowait(quote)
        except asyncio.QueueFull:
            logger.warning(
                "Chain builder queue full, dropping quote for %s",
                quote.underlying_symbol,
            )
            # Could implement backpressure strategy here

    async def _process_quotes(self) -> None:
        """Process quotes from queue into buffers."""
        while not self._shutdown_event.is_set():
            try:
                quote = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except TimeoutError:
                continue

            self._state.quotes_received += 1
            self._state.last_activity_time = time.time()

            buffer = self._get_buffer(quote.underlying_symbol, quote.expiry_epoch_day)

            # Check for sequence gaps
            if buffer.last_emitted_sequence > 0:
                expected = buffer.last_emitted_sequence + 1
                if quote.sequence > expected:
                    gap = quote.sequence - expected
                    buffer.gaps_detected += gap
                    self._state.gaps_detected += gap
                    logger.warning(
                        "Sequence gap detected for %s expiry_day=%d: expected %d, got %d (gap=%d)",
                        quote.underlying_symbol,
                        quote.expiry_epoch_day,
                        expected,
                        quote.sequence,
                        gap,
                    )
                elif quote.sequence <= buffer.last_emitted_sequence:
                    # Duplicate or out-of-order quote, skip
                    logger.debug(
                        "Duplicate/out-of-order quote for %s seq=%d (last=%d)",
                        quote.underlying_symbol,
                        quote.sequence,
                        buffer.last_emitted_sequence,
                    )
                    continue

            # Store quote keyed by sequence for ordering
            buffer.quotes[quote.sequence] = quote

            # Emit immediately if configured (for testing)
            if self._config.emit_on_every_quote:
                await self._emit_snapshot(buffer)

            self._queue.task_done()

    async def _emit_snapshot(self, buffer: _ChainBuffer) -> None:
        """Emit a snapshot from the buffer."""
        if not buffer.quotes:
            return

        # Get quotes in sequence order
        sorted_sequences = sorted(buffer.quotes.keys())
        quotes_list = [buffer.quotes[seq] for seq in sorted_sequences]

        # Create snapshot - use first quote's event_time_ns as snapshot time
        event_time_ns = quotes_list[0].event_time_ns if quotes_list else int(time.time() * 1_000_000_000)

        snapshot = OptionChainSnapshot(
            underlying_symbol=buffer.underlying_symbol,
            event_time_ns=event_time_ns,
            sequence=sorted_sequences[-1],
            quotes=tuple(quotes_list),
            reported_quote_count=len(quotes_list),
        )

        # Update buffer state
        buffer.last_emitted_sequence = sorted_sequences[-1]
        buffer.last_emit_time = time.time()
        # Clear emitted quotes from buffer
        for seq in sorted_sequences:
            del buffer.quotes[seq]

        self._state.snapshots_emitted += 1

        # Call handler
        try:
            await self._handler(snapshot)
        except (RuntimeError, ValueError, OSError) as e:
            logger.error("Handler failed for snapshot: %s", e)

    async def _emit_loop(self) -> None:
        """Periodic emission loop."""
        while not self._shutdown_event.is_set():
            await asyncio.sleep(self._config.snapshot_interval)

            if self._shutdown_event.is_set():
                break

            now = time.time()
            for buffer in list(self._state.buffers.values()):
                # Emit if buffer has quotes and interval elapsed
                if buffer.quotes and (now - buffer.last_emit_time >= self._config.snapshot_interval):
                    await self._emit_snapshot(buffer)

    async def run(self) -> None:
        """Run the chain builder until shutdown."""
        self._tasks = [
            asyncio.create_task(self._process_quotes()),
        ]
        self._emit_task = asyncio.create_task(self._emit_loop())

        try:
            await self._shutdown_event.wait()
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully shutdown and emit remaining buffers."""
        self._shutdown_event.set()

        # Emit remaining buffers
        for buffer in list(self._state.buffers.values()):
            if buffer.quotes:
                await self._emit_snapshot(buffer)

        # Cancel tasks
        for task in self._tasks:
            task.cancel()
        if self._emit_task:
            self._emit_task.cancel()

        all_tasks = self._tasks + ([self._emit_task] if self._emit_task else [])
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)

    def get_stats(self) -> dict[str, Any]:
        """Return current builder statistics."""
        return {
            "quotes_received": self._state.quotes_received,
            "snapshots_emitted": self._state.snapshots_emitted,
            "gaps_detected": self._state.gaps_detected,
            "active_buffers": len(self._state.buffers),
            "total_buffered_quotes": sum(len(b.quotes) for b in self._state.buffers.values()),
            "queue_size": self._queue.qsize(),
            "last_activity_age_sec": time.time() - self._state.last_activity_time
            if self._state.last_activity_time
            else None,
        }


# ── Convenience Runner ────────────────────────────────────────────────────────


async def run_chain_builder(
    config: ChainBuilderConfig,
    handler: ChainSnapshotHandler | None = None,
    shutdown_signal: asyncio.Event | None = None,
) -> dict[str, Any]:
    """Run chain builder until shutdown signal.

    Args:
        config: Chain builder configuration
        handler: Optional custom snapshot handler
        shutdown_signal: Optional external shutdown event

    Returns:
        Final statistics dictionary
    """
    builder = ChainBuilder(config, handler)
    shutdown = shutdown_signal or asyncio.Event()

    async def _wait_for_shutdown() -> None:
        await shutdown.wait()
        await builder.shutdown()

    await asyncio.gather(builder.run(), _wait_for_shutdown())
    return builder.get_stats()