# ─────────────────────────────────────────────────────────────────────────────
# TimescaleDB writer for OptionChainSnapshot.
#
# Uses asyncpg for async PostgreSQL/TimescaleDB I/O. Supports hypertables,
# continuous aggregates, and chunk partitioning by time.
# ─────────────────────────────────────────────────────────────────────────────

# mypy: disable-error-code="import-untyped,attr-defined"

from __future__ import annotations

import asyncio
import logging
import types
from dataclasses import dataclass
from typing import Any, Self

import asyncpg

logger = logging.getLogger(__name__)

__all__ = [
    "TimescaleConfig",
    "TimescaleConnectionPool",
    "TimescaleWriter",
]


@dataclass(frozen=True, slots=True)
class TimescaleConfig:
    """Configuration for TimescaleDB writer."""

    host: str = "localhost"
    port: int = 5432
    database: str = "volpulse"
    user: str = "volpulse"
    password: str = ""
    # Connection pool
    min_size: int = 5
    max_size: int = 20
    # Batch settings
    batch_size: int = 1000
    flush_interval: float = 1.0
    # Table names
    snapshot_table: str = "option_chain_snapshots"
    quote_table: str = "option_quotes"
    # Hypertable settings
    chunk_time_interval: str = "1 day"
    # Retention
    retention_interval: str | None = "30 days"


class TimescaleConnectionPool:
    """Async connection pool for TimescaleDB."""

    def __init__(self, config: TimescaleConfig) -> None:
        self._config = config
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Initialize the connection pool and schema."""
        self._pool = await asyncpg.create_pool(
            host=self._config.host,
            port=self._config.port,
            database=self._config.database,
            user=self._config.user,
            password=self._config.password,
            min_size=self._config.min_size,
            max_size=self._config.max_size,
        )
        await self._ensure_schema()

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def acquire(self) -> asyncpg.Connection:
        """Acquire a connection from the pool."""
        if self._pool is None:
            await self.initialize()
        # _pool is guaranteed to be non-None after initialize()
        assert self._pool is not None
        return await self._pool.acquire()

    async def release(self, conn: asyncpg.Connection) -> None:
        """Release a connection back to the pool."""
        if self._pool:
            await self._pool.release(conn)

    async def _ensure_schema(self) -> None:
        """Create tables and hypertables if they don't exist."""
        async with self.acquire() as conn:
            # Create extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

            # Create snapshot table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._config.snapshot_table} (
                    id BIGSERIAL PRIMARY KEY,
                    underlying_symbol TEXT NOT NULL,
                    event_time_ns BIGINT NOT NULL,
                    sequence BIGINT NOT NULL,
                    expiry_epoch_day INTEGER NOT NULL,
                    reported_quote_count INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            # Create quote table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._config.quote_table} (
                    id BIGSERIAL PRIMARY KEY,
                    snapshot_id BIGINT NOT NULL REFERENCES {self._config.snapshot_table}(id) ON DELETE CASCADE,
                    contract_id TEXT NOT NULL,
                    underlying_symbol TEXT NOT NULL,
                    expiry_epoch_day INTEGER NOT NULL,
                    strike DOUBLE PRECISION NOT NULL,
                    right TEXT NOT NULL,
                    bid DOUBLE PRECISION NOT NULL,
                    ask DOUBLE PRECISION NOT NULL,
                    last_price DOUBLE PRECISION NOT NULL,
                    close_price DOUBLE PRECISION NOT NULL,
                    implied_volatility DOUBLE PRECISION NOT NULL,
                    event_time_ns BIGINT NOT NULL,
                    ingest_time_ns BIGINT NOT NULL,
                    sequence BIGINT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            # Create indexes
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self._config.snapshot_table}_symbol_time
                ON {self._config.snapshot_table} (underlying_symbol, event_time_ns DESC);
            """)

            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self._config.quote_table}_snapshot
                ON {self._config.quote_table} (snapshot_id);
            """)

            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self._config.quote_table}_symbol_time
                ON {self._config.quote_table} (underlying_symbol, event_time_ns DESC);
            """)

            # Convert to hypertables
            try:
                await conn.execute(f"""
                    SELECT create_hypertable(
                        '{self._config.snapshot_table}',
                        'event_time_ns',
                        chunk_time_interval => {self._config.chunk_time_interval}::interval,
                        if_not_exists => TRUE
                    );
                """)
            except (asyncpg.PostgresError, OSError) as e:
                logger.warning("Hypertable creation for snapshots may already exist: %s", e)

            try:
                await conn.execute(f"""
                    SELECT create_hypertable(
                        '{self._config.quote_table}',
                        'event_time_ns',
                        chunk_time_interval => {self._config.chunk_time_interval}::interval,
                        if_not_exists => TRUE
                    );
                """)
            except (asyncpg.PostgresError, OSError) as e:
                logger.warning("Hypertable creation for quotes may already exist: %s", e)

            # Add retention policy if configured
            if self._config.retention_interval:
                try:
                    await conn.execute(f"""
                        SELECT add_retention_policy(
                            '{self._config.snapshot_table}',
                            INTERVAL '{self._config.retention_interval}',
                            if_not_exists => TRUE
                        );
                    """)
                    await conn.execute(f"""
                        SELECT add_retention_policy(
                            '{self._config.quote_table}',
                            INTERVAL '{self._config.retention_interval}',
                            if_not_exists => TRUE
                        );
                    """)
                except (asyncpg.PostgresError, OSError) as e:
                    logger.warning("Retention policy may already exist: %s", e)

            # Create continuous aggregate for 1-minute OHLC
            try:
                await conn.execute(f"""
                    CREATE MATERIALIZED VIEW IF NOT EXISTS option_quotes_1m
                    WITH (timescaledb.continuous) AS
                    SELECT
                        time_bucket('1 minute', to_timestamp(event_time_ns / 1e9)) AS bucket,
                        underlying_symbol,
                        strike,
                        right,
                        FIRST(bid, event_time_ns) AS open_bid,
                        MAX(bid) AS high_bid,
                        MIN(bid) AS low_bid,
                        LAST(bid, event_time_ns) AS close_bid,
                        FIRST(ask, event_time_ns) AS open_ask,
                        MAX(ask) AS high_ask,
                        MIN(ask) AS low_ask,
                        LAST(ask, event_time_ns) AS close_ask,
                        COUNT(*) AS tick_count
                    FROM {self._config.quote_table}
                    GROUP BY bucket, underlying_symbol, strike, right
                    WITH NO DATA;
                """)
                await conn.execute("""
                    SELECT add_continuous_aggregate_policy('option_quotes_1m',
                        start_offset => INTERVAL '3 minutes',
                        end_offset => INTERVAL '1 minute',
                        schedule_interval => INTERVAL '1 minute',
                        if_not_exists => TRUE
                    );
                """)
            except (asyncpg.PostgresError, OSError) as e:
                logger.warning("Continuous aggregate may already exist: %s", e)


class TimescaleWriter:
    """Writes OptionChainSnapshot to TimescaleDB."""

    def __init__(
        self,
        config: TimescaleConfig,
        pool: TimescaleConnectionPool | None = None,
    ) -> None:
        self._config = config
        self._pool = pool or TimescaleConnectionPool(config)
        self._batch_queue: list[Any] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._running = False

    async def initialize(self) -> None:
        """Initialize the writer and start flush task."""
        await self._pool.initialize()
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def close(self) -> None:
        """Flush remaining batch and close pool."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self.flush()
        await self._pool.close()

    async def write_snapshot(self, snapshot: Any) -> None:
        """Queue a snapshot for async writing."""
        self._batch_queue.append(snapshot)
        if len(self._batch_queue) >= self._config.batch_size:
            await self.flush()

    async def flush(self) -> None:
        """Flush the batch queue to database."""
        if not self._batch_queue:
            return

        batch = self._batch_queue[:self._config.batch_size]
        self._batch_queue = self._batch_queue[self._config.batch_size:]

        conn = await self._pool.acquire()
        async with conn, conn.transaction():
            for snapshot in batch:
                await self._insert_snapshot(conn, snapshot)

    async def _insert_snapshot(self, conn: asyncpg.Connection, snapshot: Any) -> None:
        """Insert a single snapshot and its quotes."""
        # Insert snapshot
        snapshot_id = await conn.fetchval(f"""
            INSERT INTO {self._config.snapshot_table}
            (underlying_symbol, event_time_ns, sequence, expiry_epoch_day, reported_quote_count)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """,
            snapshot.underlying_symbol,
            snapshot.quotes[0].event_time_ns if snapshot.quotes else 0,
            snapshot.sequence,
            snapshot.quotes[0].expiry_epoch_day if snapshot.quotes else 0,
            snapshot.reported_quote_count,
        )

        # Insert quotes
        if snapshot.quotes:
            records = [
                (
                    snapshot_id,
                    q.contract_id,
                    q.underlying_symbol,
                    q.expiry_epoch_day,
                    q.strike,
                    q.right.value,
                    q.bid,
                    q.ask,
                    q.last,
                    q.close,
                    q.implied_volatility,
                    q.event_time_ns,
                    q.ingest_time_ns,
                    q.sequence,
                    q.source.value,
                )
                for q in snapshot.quotes
            ]

            await conn.copy_records_to_table(
                self._config.quote_table,
                records=records,
                columns=[
                    "snapshot_id", "contract_id", "underlying_symbol",
                    "expiry_epoch_day", "strike", "right", "bid", "ask",
                    "last_price", "close_price", "implied_volatility",
                    "event_time_ns", "ingest_time_ns", "sequence", "source"
                ],
            )

    async def _flush_loop(self) -> None:
        """Periodic flush loop."""
        while True:
            try:
                await asyncio.sleep(self._config.flush_interval)
                if self._batch_queue:
                    await self.flush()
            except asyncio.CancelledError:
                break
            except (OSError, asyncpg.PostgresError) as e:
                logger.error("Flush loop error: %s", e)

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
