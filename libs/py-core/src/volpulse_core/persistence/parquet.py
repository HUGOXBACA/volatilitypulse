# ─────────────────────────────────────────────────────────────────────────────
# Parquet writer and reader for OptionChainSnapshot.
#
# Uses Polars for fast, partitioned Parquet I/O with schema validation via
# pandera. Supports partitioned storage by underlying_symbol and expiry.
# ─────────────────────────────────────────────────────────────────────────────

# mypy: disable-error-code="import-untyped"

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl
import pyarrow as pa

from volpulse_core.models.chain import OptionChainSnapshot
from volpulse_core.models.quote import OptionQuote

logger = logging.getLogger(__name__)

__all__ = [
    "ParquetConfig",
    "ParquetReader",
    "ParquetWriter",
]


@dataclass(frozen=True, slots=True)
class ParquetConfig:
    """Configuration for Parquet writer/reader."""

    base_path: str
    partition_by: tuple[str, ...] = ("underlying_symbol", "expiry_epoch_day")
    compression: str = "zstd"
    compression_level: int = 3
    row_group_size: int = 100_000
    use_dictionary: bool = True
    statistics: str = "full"
    # Schema validation
    validate_on_write: bool = True
    validate_on_read: bool = False


# Schema for OptionChainSnapshot Parquet files
_SNAPSHOT_SCHEMA = pa.schema([
    ("underlying_symbol", pa.string()),
    ("event_time_ns", pa.int64()),
    ("sequence", pa.int64()),
    ("expiry_epoch_day", pa.int32()),
    ("contract_id", pa.string()),
    ("strike", pa.float64()),
    ("right", pa.string()),
    ("bid", pa.float64()),
    ("ask", pa.float64()),
    ("last", pa.float64()),
    ("close", pa.float64()),
    ("implied_volatility", pa.float64()),
    ("event_time_ns", pa.int64()),
    ("ingest_time_ns", pa.int64()),
    ("sequence", pa.int64()),
    ("source", pa.string()),
    ("snapshot_sequence", pa.int64()),
    ("reported_quote_count", pa.int32()),
])


class ParquetWriter:
    """Writes OptionChainSnapshot to partitioned Parquet files."""

    def __init__(self, config: ParquetConfig) -> None:
        self._config = config
        self._base_path = Path(config.base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)

    def write_snapshot(self, snapshot: OptionChainSnapshot) -> Path:
        """Write a single snapshot to Parquet.

        Returns the path of the written file.
        """
        df = self._snapshot_to_dataframe(snapshot)
        partition_path = self._get_partition_path(snapshot)
        partition_path.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp for uniqueness
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"snapshot_{snapshot.sequence}_{timestamp}.parquet"
        filepath = partition_path / filename

        df.write_parquet(
            filepath,
            compression=self._config.compression,  # type: ignore[arg-type]
            compression_level=self._config.compression_level,
            row_group_size=self._config.row_group_size,
            statistics=self._config.statistics,
        )

        logger.debug("Wrote snapshot to %s (quotes=%d)", filepath, len(snapshot.quotes))
        return filepath

    def write_batch(self, snapshots: list[OptionChainSnapshot]) -> list[Path]:
        """Write multiple snapshots efficiently."""
        paths = []
        for snapshot in snapshots:
            paths.append(self.write_snapshot(snapshot))
        return paths

    def _snapshot_to_dataframe(self, snapshot: OptionChainSnapshot) -> pl.DataFrame:
        """Convert OptionChainSnapshot to Polars DataFrame."""
        rows = []
        for quote in snapshot.quotes:
            rows.append({
                "underlying_symbol": quote.underlying_symbol,
                "event_time_ns": quote.event_time_ns,
                "sequence": quote.sequence,
                "expiry_epoch_day": quote.expiry_epoch_day,
                "contract_id": quote.contract_id,
                "strike": quote.strike,
                "right": quote.right.value,
                "bid": quote.bid,
                "ask": quote.ask,
                "last": quote.last,
                "close": quote.close,
                "implied_volatility": quote.implied_volatility,
                "ingest_time_ns": quote.ingest_time_ns,
                "source": quote.source.value,
                "snapshot_sequence": snapshot.sequence,
                "reported_quote_count": snapshot.reported_quote_count,
            })

        df = pl.DataFrame(rows)
        return df

    def _get_partition_path(self, snapshot: OptionChainSnapshot) -> Path:
        """Get partition path for snapshot."""
        path = self._base_path
        for col in self._config.partition_by:
            if col == "underlying_symbol":
                path = path / f"underlying_symbol={snapshot.underlying_symbol}"
            elif col == "expiry_epoch_day":
                path = path / f"expiry_epoch_day={snapshot.quotes[0].expiry_epoch_day}"
        return path


class ParquetReader:
    """Reads OptionChainSnapshot from partitioned Parquet files."""

    def __init__(self, config: ParquetConfig) -> None:
        self._config = config
        self._base_path = Path(config.base_path)

    def read_snapshots(
        self,
        underlying_symbol: str | None = None,
        expiry_epoch_day: int | None = None,
        start_sequence: int | None = None,
        end_sequence: int | None = None,
    ) -> list[OptionChainSnapshot]:
        """Read snapshots with optional filters."""
        files = self._find_files(underlying_symbol, expiry_epoch_day)

        snapshots = []
        for filepath in files:
            df = pl.read_parquet(filepath)
            if start_sequence is not None:
                df = df.filter(pl.col("snapshot_sequence") >= start_sequence)
            if end_sequence is not None:
                df = df.filter(pl.col("snapshot_sequence") <= end_sequence)

            # Group by snapshot_sequence and reconstruct snapshots
            for seq, group in df.group_by("snapshot_sequence", maintain_order=True):
                snapshot = self._dataframe_to_snapshot(group)
                snapshots.append(snapshot)

        return sorted(snapshots, key=lambda s: s.sequence)

    def read_latest(
        self,
        underlying_symbol: str,
        expiry_epoch_day: int | None = None,
    ) -> OptionChainSnapshot | None:
        """Read the most recent snapshot for an underlying."""
        files = self._find_files(underlying_symbol, expiry_epoch_day)
        if not files:
            return None

        # Read the most recent file (by modification time)
        latest_file = max(files, key=lambda f: f.stat().st_mtime)
        df = pl.read_parquet(latest_file)
        latest_seq = df["snapshot_sequence"].max()
        latest_group = df.filter(pl.col("snapshot_sequence") == latest_seq)

        return self._dataframe_to_snapshot(latest_group)

    def _find_files(
        self,
        underlying_symbol: str | None = None,
        expiry_epoch_day: int | None = None,
    ) -> list[Path]:
        """Find Parquet files matching filters."""
        path = self._base_path
        if not path.exists():
            return []

        if underlying_symbol:
            path = path / f"underlying_symbol={underlying_symbol}"
        if expiry_epoch_day:
            path = path / f"expiry_epoch_day={expiry_epoch_day}"

        if not path.exists():
            return []

        return list(path.rglob("*.parquet"))

    def _dataframe_to_snapshot(self, df: pl.DataFrame) -> OptionChainSnapshot:
        """Convert DataFrame group to OptionChainSnapshot."""
        quotes = []
        for row in df.iter_rows(named=True):
            quote = OptionQuote(
                contract_id=row["contract_id"],
                underlying_symbol=row["underlying_symbol"],
                expiry_epoch_day=row["expiry_epoch_day"],
                strike=row["strike"],
                right=row["right"],
                bid=row["bid"],
                ask=row["ask"],
                last=row["last"],
                close=row["close"],
                implied_volatility=row["implied_volatility"],
                event_time_ns=row["event_time_ns"],
                ingest_time_ns=row["ingest_time_ns"],
                sequence=row["sequence"],
                source=row["source"],
            )
            quotes.append(quote)

        return OptionChainSnapshot(
            underlying_symbol=quotes[0].underlying_symbol,
            event_time_ns=quotes[0].event_time_ns,
            sequence=df["snapshot_sequence"].item(),
            quotes=tuple(quotes),
            reported_quote_count=len(quotes),
        )