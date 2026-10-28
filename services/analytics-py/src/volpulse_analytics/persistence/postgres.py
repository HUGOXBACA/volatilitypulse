"""Relational persistence (PostgreSQL) for portfolio and system state.

The relational store holds the things that are *updated*, not appended: open
positions, portfolio metadata, ingestion checkpoints and the record of which
signals have already been fired.

Signals are the subtle part. A signal that has been acted on must never be
emitted again, so the write of the signal and the write of the portfolio
state happen in one transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["PostgresWriter", "postgres_ddl"]


#: Schema of the relational store. Executed idempotently at startup.
postgres_ddl: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS positions (
        contract_id        text        PRIMARY KEY,
        underlying_symbol  text        NOT NULL,
        strike             double precision NOT NULL,
        right              text        NOT NULL,
        quantity           double precision NOT NULL,
        avg_entry_price    double precision NOT NULL,
        opened_at          timestamptz NOT NULL,
        updated_at         timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    INSERT INTO positions
    (contract_id, underlying_symbol, strike, right, quantity, avg_entry_price, opened_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (contract_id) DO UPDATE SET
        quantity = EXCLUDED.quantity,
        avg_entry_price = EXCLUDED.avg_entry_price,
        updated_at = now()
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolios (
        portfolio_id text PRIMARY KEY,
        description  text NOT NULL,
        created_at   timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ingestion_checkpoints (
        topic         text        NOT NULL,
        partition     integer     NOT NULL,
        offset        bigint      NOT NULL,
        updated_at    timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (topic, partition)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS emitted_signals (
        signal_id      uuid        PRIMARY KEY,
        portfolio_id   text        NOT NULL,
        underlying_symbol text     NOT NULL,
        contract_id    text        NOT NULL,
        kind           text        NOT NULL,
        zscore         double precision NOT NULL,
        emitted_at     timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS emitted_signals_lookup "
    "ON emitted_signals (contract_id, kind, emitted_at)",
    """
    INSERT INTO ingestion_checkpoints (topic, partition, offset)
    VALUES (%s, %s, %s)
    ON CONFLICT (topic, partition) DO UPDATE SET
        offset = EXCLUDED.offset,
        updated_at = now()
    """,
)


@dataclass(frozen=True, slots=True)
class PostgresConnection:
    """Connection parameters for the relational store."""

    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_settings(cls, settings: Any) -> PostgresConnection:
        """Build the connection parameters from the service settings."""
        return cls(
            host=settings.postgres_host,
            port=settings.postgres_port,
            database=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
        )


class PostgresWriter:
    """Writer for the relational store."""

    __slots__ = ("_connection",)

    def __init__(self, connection: PostgresConnection) -> None:
        """Store the connection parameters.

        The connection is opened lazily by :meth:`connect`.
        """
        self._connection = connection

    def connect(self) -> Any:
        """Open a connection and make sure the schema exists.

        Returns:
            An open psycopg connection.

        Raises:
            psycopg.Error: The database rejected the connection or the DDL.
        """
        import psycopg  # noqa: PLC0415  - imported lazily: psycopg is only needed to connect

        connection = psycopg.connect(
            host=self._connection.host,
            port=self._connection.port,
            dbname=self._connection.database,
            user=self._connection.user,
            password=self._connection.password,
            autocommit=True,
        )
        with connection.cursor() as cursor:
            for statement in postgres_ddl:
                cursor.execute(statement)
        return connection

    def upsert_positions(self, connection: Any, rows: Sequence[tuple[Any, ...]]) -> int:
        """Insert or update the open positions of a portfolio.

        Args:
            connection: An open connection.
            rows: Tuples matching the column order of ``positions``.

        Returns:
            The number of positions written.
        """
        if not rows:
            return 0

        statement = """
            INSERT INTO positions (
                contract_id, underlying_symbol, strike, right,
                quantity, avg_entry_price, opened_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (contract_id) DO UPDATE SET
                quantity = EXCLUDED.quantity,
                avg_entry_price = EXCLUDED.avg_entry_price,
                updated_at = now()
        """
        with connection.cursor() as cursor:
            cursor.executemany(statement, rows)
        return len(rows)

    def save_checkpoint(self, connection: Any, topic: str, partition: int, offset: int) -> None:
        """Record the broker offset the consumer has processed.

        Args:
            connection: An open connection.
            topic: Broker topic.
            partition: Broker partition.
            offset: Last processed offset.
        """
        statement = """
            INSERT INTO ingestion_checkpoints (topic, partition, offset)
            VALUES (%s, %s, %s)
            ON CONFLICT (topic, partition) DO UPDATE SET
                offset = EXCLUDED.offset,
                updated_at = now()
        """
        with connection.cursor() as cursor:
            cursor.execute(statement, (topic, partition, offset))

    def record_signal(self, connection: Any, row: tuple[Any, ...]) -> None:
        """Record a signal that has been emitted.

        Args:
            connection: An open connection.
            row: Tuple matching the column order of ``emitted_signals``.
        """
        statement = """
            INSERT INTO emitted_signals (
                signal_id, portfolio_id, underlying_symbol, contract_id, kind, zscore
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (signal_id) DO NOTHING
        """
        with connection.cursor() as cursor:
            cursor.execute(statement, row)
