# ─────────────────────────────────────────────────────────────────────────────
# Unified snapshot writer with pluggable backends.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging
import types
from dataclasses import dataclass
from typing import Any, Self

from volpulse_core.persistence.parquet import (
    ParquetConfig,
    ParquetReader,
    ParquetWriter,
)
from volpulse_core.persistence.timescale import (
    TimescaleConfig,
    TimescaleConnectionPool,
    TimescaleWriter,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SnapshotConfig",
    "SnapshotWriter",
]


@dataclass(frozen=True, slots=True)
class SnapshotConfig:
    """Configuration for unified snapshot writer."""

    # Parquet settings
    parquet_enabled: bool = True
    parquet_config: ParquetConfig | None = None

    # TimescaleDB settings
    timescale_enabled: bool = False
    timescale_config: TimescaleConfig | None = None

    # Batch settings
    batch_size: int = 100
    flush_interval: float = 1.0


class SnapshotWriter:
    """Unified snapshot writer with pluggable backends."""

    def __init__(self, config: SnapshotConfig) -> None:
        self._config = config
        self._parquet_writer: ParquetWriter | None = None
        self._parquet_reader: ParquetReader | None = None
        self._timescale_pool: TimescaleConnectionPool | None = None
        self._timescale_writer: TimescaleWriter | None = None
        self._batch_queue: list[Any] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._running = False

        # Initialize backends
        if config.parquet_enabled and config.parquet_config:
            pc = config.parquet_config if isinstance(config.parquet_config, ParquetConfig) else ParquetConfig(**config.parquet_config)
            self._parquet_writer = ParquetWriter(pc)
            self._parquet_reader = ParquetReader(pc)

        if config.timescale_enabled and config.timescale_config:
            from volpulse_core.persistence.timescale import TimescaleConfig as TC
            from volpulse_core.persistence.timescale import (
                TimescaleConnectionPool,
                TimescaleWriter,
            )
            tc = config.timescale_config if isinstance(config.timescale_config, TimescaleConfig) else TC(**config.timescale_config)
            self._timescale_pool = TimescaleConnectionPool(tc)
            self._timescale_writer = TimescaleWriter(tc)

    async def initialize(self) -> None:
        """Initialize all enabled backends."""
        if self._timescale_writer:
            await self._timescale_writer.initialize()

        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def close(self) -> None:
        """Close all backends."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush any remaining
        if hasattr(self, '_batch_queue') and self._batch_queue:
            await self._flush_parquet()
            if self._timescale_writer:
                await self._timescale_writer.flush()

        # Close backends
        if self._timescale_writer:
            await self._timescale_writer.close()

    async def write_snapshot(self, snapshot: Any) -> None:
        """Write snapshot to all enabled backends."""
        # Write to Parquet immediately (fast)
        if self._parquet_writer:
            try:
                self._parquet_writer.write_snapshot(snapshot)
            except (OSError, ValueError) as e:
                logger.error("Parquet write failed: %s", e)

        # Queue for TimescaleDB batch write
        if self._timescale_writer:
            await self._timescale_writer.write_snapshot(snapshot)

    async def flush(self) -> None:
        """Flush all backends."""
        await self._flush_parquet()
        if self._timescale_writer:
            await self._timescale_writer.flush()

    async def _flush_parquet(self) -> None:
        """Parquet writes are immediate, nothing to flush."""

    async def _flush_loop(self) -> None:
        """Periodic flush loop for TimescaleDB."""
        while self._running:
            try:
                await asyncio.sleep(self._config.flush_interval)
                if self._batch_queue:
                    await self.flush()
            except asyncio.CancelledError:
                break
            except (OSError, ValueError) as e:
                logger.error("Flush loop error: %s", e)

    def get_reader(self) -> Any | None:
        """Get Parquet reader for querying snapshots."""
        return self._parquet_reader

    async def __aenter__(self) -> Self:
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        await self.close()