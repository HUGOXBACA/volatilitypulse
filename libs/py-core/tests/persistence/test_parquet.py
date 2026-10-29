# ─────────────────────────────────────────────────────────────────────────────
# Tests for Parquet persistence layer.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest

from volpulse_core.models.chain import OptionChainSnapshot
from volpulse_core.models.quote import OptionQuote, OptionRight, QuoteSource
from volpulse_core.persistence.parquet import ParquetConfig, ParquetReader, ParquetWriter


def _make_snapshot(sequence: int = 1, n_quotes: int = 5) -> OptionChainSnapshot:
    """Create a test snapshot with n_quotes."""
    quotes = []
    for i in range(n_quotes):
        quotes.append(
            OptionQuote(
                contract_id=f"AAPL240119C00150000_{i}",
                underlying_symbol="AAPL",
                expiry_epoch_day=20000,
                strike=150.0 + i,
                right=OptionRight.CALL if i % 2 == 0 else OptionRight.PUT,
                bid=1.0 + i * 0.1,
                ask=1.1 + i * 0.1,
                last=1.05 + i * 0.1,
                close=1.0 + i * 0.1,
                implied_volatility=0.25 + i * 0.01,
                event_time_ns=1_700_000_000_000_000_000 + i * 1_000_000,
                ingest_time_ns=1_700_000_000_000_000_000 + i * 1_000_000 + 1000,
                sequence=i + 1,
                source=QuoteSource.REALTIME_FEED,
            )
        )
    return OptionChainSnapshot(
        underlying_symbol="AAPL",
        event_time_ns=1_700_000_000_000_000_000,
        sequence=sequence,
        quotes=tuple(quotes),
        reported_quote_count=n_quotes,
    )


class TestParquetConfig:
    """Tests for ParquetConfig."""

    def test_default_config(self) -> None:
        config = ParquetConfig(base_path="/tmp/test")
        assert config.base_path == "/tmp/test"
        assert config.partition_by == ("underlying_symbol", "expiry_epoch_day")
        assert config.compression == "zstd"
        assert config.compression_level == 3

    def test_custom_config(self) -> None:
        config = ParquetConfig(
            base_path="/data",
            partition_by=("underlying_symbol",),
            compression="snappy",
            compression_level=5,
        )
        assert config.partition_by == ("underlying_symbol",)
        assert config.compression == "snappy"
        assert config.compression_level == 5


class TestParquetWriter:
    """Tests for ParquetWriter."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> ParquetConfig:
        return ParquetConfig(base_path=str(tmp_path))

    @pytest.fixture
    def writer(self, config: ParquetConfig) -> ParquetWriter:
        return ParquetWriter(config)

    @pytest.fixture
    def snapshot(self) -> "OptionChainSnapshot":
        return _make_snapshot(sequence=1, n_quotes=3)

    def test_write_snapshot(self, writer: ParquetWriter, snapshot: "OptionChainSnapshot") -> None:
        path = writer.write_snapshot(snapshot)
        assert path.exists()
        assert path.suffix == ".parquet"

    def test_write_batch(self, writer: ParquetWriter, snapshot: "OptionChainSnapshot") -> None:
        snapshots = [_make_snapshot(seq, 2) for seq in range(3)]
        paths = writer.write_batch(snapshots)
        assert len(paths) == 3
        for p in paths:
            assert p.exists()

    def test_partition_path(self, writer: ParquetWriter, snapshot: "OptionChainSnapshot") -> None:
        # Access private method for testing
        path = writer._get_partition_path(snapshot)
        assert "underlying_symbol=AAPL" in str(path)
        assert "expiry_epoch_day=20000" in str(path)


class TestParquetReader:
    """Tests for ParquetReader."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> ParquetConfig:
        return ParquetConfig(base_path=str(tmp_path))

    @pytest.fixture
    def writer(self, config: ParquetConfig) -> ParquetWriter:
        return ParquetWriter(config)

    @pytest.fixture
    def reader(self, config: ParquetConfig) -> ParquetReader:
        return ParquetReader(config)

    @pytest.fixture
    def snapshots(self, writer: ParquetWriter) -> list:
        snapshots = [_make_snapshot(seq, 2) for seq in range(5)]
        for s in snapshots:
            writer.write_snapshot(s)
        return snapshots

    def test_read_snapshots(self, reader: ParquetReader, snapshots: list) -> None:
        read_snapshots = reader.read_snapshots()
        assert len(read_snapshots) == 5

    def test_read_snapshots_filter_underlying(self, reader: ParquetReader, snapshots: list) -> None:
        # All snapshots are AAPL
        read_snapshots = reader.read_snapshots(underlying_symbol="AAPL")
        assert len(read_snapshots) == 5

        # Non-existent underlying
        read_snapshots = reader.read_snapshots(underlying_symbol="MSFT")
        assert len(read_snapshots) == 0

    def test_read_snapshots_filter_sequence(self, reader: ParquetReader, snapshots: list) -> None:
        read_snapshots = reader.read_snapshots(start_sequence=2, end_sequence=4)
        assert len(read_snapshots) == 3
        sequences = [s.sequence for s in read_snapshots]
        assert sequences == [2, 3, 4]

    def test_read_latest(self, reader: ParquetReader, snapshots: list) -> None:
        latest = reader.read_latest("AAPL")
        assert latest is not None
        assert latest.sequence == 4  # Latest sequence (0-4)

    def test_read_latest_none(self, reader: ParquetReader) -> None:
        # No snapshots for MSFT
        latest = reader.read_latest("MSFT")
        assert latest is None


class TestParquetSchema:
    """Tests for Parquet schema validation."""

    def test_snapshot_schema(self, tmp_path: Path) -> None:
        config = ParquetConfig(base_path=str(tmp_path), validate_on_write=True)
        writer = ParquetWriter(config)
        snapshot = _make_snapshot(1, 3)
        path = writer.write_snapshot(snapshot)

        # Read back and verify schema
        df = pl.read_parquet(path)
        assert "underlying_symbol" in df.columns
        assert "strike" in df.columns
        assert "implied_volatility" in df.columns
        assert len(df) == 3


class TestParquetConfigValidation:
    """Tests for ParquetConfig validation."""

    def test_invalid_base_path(self) -> None:
        # Path doesn't need to exist at config creation
        config = ParquetConfig(base_path="/nonexistent/path")
        assert config.base_path == "/nonexistent/path"

    def test_compression_options(self) -> None:
        for comp in ["zstd", "snappy", "gzip", "lz4"]:
            config = ParquetConfig(base_path="/tmp", compression=comp)
            assert config.compression == comp


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot writer tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSnapshotWriter:
    """Tests for unified SnapshotWriter."""

    @pytest.fixture
    def config(self, tmp_path: Path):
        from volpulse_core.persistence.snapshot import SnapshotConfig
        return SnapshotConfig(
            parquet_enabled=True,
            parquet_config={"base_path": str(tmp_path)},
            timescale_enabled=False,
        )

    @pytest.fixture
    def writer(self, config):
        from volpulse_core.persistence.snapshot import SnapshotWriter
        return SnapshotWriter(config)

    @pytest.fixture
    def snapshot(self):
        return _make_snapshot(1, 3)

    @pytest.mark.asyncio
    async def test_write_snapshot_parquet(self, writer, snapshot, tmp_path: Path):
        await writer.initialize()
        await writer.write_snapshot(snapshot)

        # Verify file was written
        files = list(Path(writer._parquet_writer._config.base_path).rglob("*.parquet"))
        assert len(files) >= 1

    @pytest.mark.asyncio
    async def test_write_snapshot_batch(self, writer, tmp_path: Path):
        await writer.initialize()
        snapshots = [_make_snapshot(seq, 2) for seq in range(3)]
        for s in snapshots:
            await writer.write_snapshot(s)

        files = list(Path(writer._parquet_writer._config.base_path).rglob("*.parquet"))
        assert len(files) >= 3

    @pytest.mark.asyncio
    async def test_close_flushes(self, writer, snapshot):
        await writer.initialize()
        await writer.write_snapshot(snapshot)
        await writer.close()
        # Should not raise


# ─────────────────────────────────────────────────────────────────────────────
# TimescaleDB schema tests (mocked)
# ─────────────────────────────────────────────────────────────────────────────


class TestTimescaleSchema:
    """Tests for TimescaleDB DDL generation."""

    def test_timescale_ddl_snapshot_table(self) -> None:
        from volpulse_core.persistence.timescale import TimescaleConfig
        config = TimescaleConfig()
        # Schema should contain snapshot table
        assert "snapshot_table" in dir(TimescaleConfig)

    def test_timescale_ddl_quote_table(self) -> None:
        from volpulse_core.persistence.timescale import TimescaleConfig
        config = TimescaleConfig()
        assert config.quote_table == "option_quotes"


# ─────────────────────────────────────────────────────────────────────────────
# Mock-based TimescaleDB tests (no DB required)
# ─────────────────────────────────────────────────────────────────────────────


class TestTimescaleWriterMock:
    """Mock-based tests for TimescaleWriter."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.acquire = MagicMock()
        pool.release = MagicMock()
        return pool

    @pytest.fixture
    def writer(self, mock_pool):
        from volpulse_core.persistence.timescale import TimescaleConfig, TimescaleWriter
        config = TimescaleConfig()
        writer = TimescaleWriter(config)
        writer._pool = mock_pool
        return writer

    @pytest.mark.asyncio
    async def test_write_snapshot_queues(self, writer, mock_pool):
        from volpulse_core.models.chain import OptionChainSnapshot
        from volpulse_core.models.quote import OptionQuote, OptionRight, QuoteSource

        snapshot = _make_snapshot(1, 2)
        mock_conn = MagicMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        mock_conn.transaction.return_value.__aenter__.return_value = mock_conn
        mock_conn.transaction.return_value.__aexit__.return_value = None
        mock_conn.fetchval.return_value = 1
        mock_conn.copy_records_to_table = MagicMock()

        await writer.write_snapshot(snapshot)

        # Should queue the snapshot
        assert len(writer._batch_queue) == 1

    @pytest.mark.asyncio
    async def test_flush_calls_insert(self, writer, mock_pool):
        from volpulse_core.models.chain import OptionChainSnapshot
        from volpulse_core.models.quote import OptionQuote, OptionRight, QuoteSource

        snapshot = _make_snapshot(1, 2)
        writer._batch_queue.append(snapshot)

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=mock_conn)
        mock_pool.acquire = AsyncMock(return_value=mock_conn)

        await writer.flush()

        # Should have called insert
        assert mock_pool.acquire.called
        assert mock_conn.fetchval.called
        assert mock_conn.copy_records_to_table.called