"""Time-series persistence (TimescaleDB).

Ticks, fitted surfaces and Greeks belong in the time-series store: they are
append-only, queried by time range, and far too large for a relational
table.

Bulk writes go through PostgreSQL's ``COPY`` protocol rather than a
statement per row: a single snapshot of a wide option chain is tens of
thousands of rows, and row-by-row inserts would dominate the latency budget.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["TimescaleWriter", "timescale_ddl"]


#: Schema of the time-series store. Executed idempotently at startup.
timescale_ddl: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS option_quotes (
        contract_id         text        NOT NULL,
        underlying_symbol   text        NOT NULL,
        expiry_epoch_day    integer     NOT NULL,
        strike              double precision NOT NULL,
        right               text        NOT NULL,
        bid                 double precision NOT NULL,
        ask                 double precision NOT NULL,
        last                double precision NOT NULL,
        close               double precision NOT NULL,
        implied_volatility  double precision,
        event_time          timestamptz NOT NULL,
        ingest_time         timestamptz NOT NULL,
        sequence            bigint      NOT NULL,
        source              text        NOT NULL,
        PRIMARY KEY (contract_id, event_time)
    )
    """,
    "SELECT create_hypertable('option_quotes', 'event_time', if_not_exists => TRUE)",
    """
    CREATE TABLE IF NOT EXISTS volatility_surfaces (
        underlying_symbol text        NOT NULL,
        as_of             timestamptz NOT NULL,
        expiry_epoch_day  integer     NOT NULL,
        strike            double precision NOT NULL,
        implied_volatility double precision NOT NULL,
        fit_method        text        NOT NULL,
        rms_error         double precision NOT NULL,
        arbitrage_free    boolean     NOT NULL,
        PRIMARY KEY (underlying_symbol, as_of, expiry_epoch_day, strike)
    )
    """,
    "SELECT create_hypertable('volatility_surfaces', 'as_of', if_not_exists => TRUE)",
    """
    CREATE TABLE IF NOT EXISTS portfolio_risk (
        portfolio_id  text        NOT NULL,
        as_of         timestamptz NOT NULL,
        delta         double precision NOT NULL,
        gamma         double precision NOT NULL,
        vega          double precision NOT NULL,
        theta         double precision NOT NULL,
        rho           double precision NOT NULL,
        gross_notional double precision NOT NULL,
        net_notional   double precision NOT NULL,
        PRIMARY KEY (portfolio_id, as_of)
    )
    """,
    "SELECT create_hypertable('portfolio_risk', 'as_of', if_not_exists => TRUE)",
)


@dataclass(frozen=True, slots=True)
class TimescaleConnection:
    """Connection parameters for the time-series store."""

    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_settings(cls, settings: Any) -> TimescaleConnection:
        """Build the connection parameters from the service settings."""
        return cls(
            host=settings.timescale_host,
            port=settings.timescale_port,
            database=settings.timescale_db,
            user=settings.timescale_user,
            password=settings.timescale_password,
        )


def _insert_statement(table: str, columns: Sequence[str]) -> Any:
    """Build an ``INSERT INTO <table> (...) VALUES (...) ON CONFLICT DO UPDATE``.

    The identifiers are composed with psycopg's ``sql`` module, and the
    upsert clause is a fixed literal that names the columns explicitly.

    Args:
        table: Name of the destination table.
        columns: Column names, in order.

    Returns:
        A psycopg composable statement.
    """
    from psycopg import sql  # noqa: PLC0415  - imported lazily, psycopg is only needed to write

    updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns[2:])
    return sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO UPDATE SET {}").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        sql.SQL(updates),
    )


def _copy_statement(table: str, columns: Sequence[str]) -> Any:
    """Build a ``COPY <table> (<columns>) FROM STDIN`` statement.

    The identifiers are composed with psycopg's ``sql`` module rather than
    interpolated into a string, so the statement is correct by construction
    rather than by inspection.

    Args:
        table: Name of the destination table.
        columns: Column names, in order.

    Returns:
        A psycopg composable statement.
    """
    from psycopg import sql  # noqa: PLC0415  - imported lazily, psycopg is only needed to write

    return sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
    )


class TimescaleWriter:
    """Bulk writer for the time-series store."""

    __slots__ = ("_connection",)

    def __init__(self, connection: TimescaleConnection) -> None:
        """Store the connection parameters.

        The connection itself is opened lazily by :meth:`connect`, so that
        constructing the writer never blocks the consumer on the database.
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
            for statement in timescale_ddl:
                cursor.execute(statement)
        return connection

    def write_quotes(self, connection: Any, rows: Sequence[tuple[Any, ...]]) -> int:
        """Write normalised quotes with the COPY protocol.

        Args:
            connection: An open connection.
            rows: Tuples matching the column order of ``option_quotes``.

        Returns:
            The number of rows written.
        """
        if not rows:
            return 0

        columns = (
            "contract_id",
            "underlying_symbol",
            "expiry_epoch_day",
            "strike",
            "right",
            "bid",
            "ask",
            "last",
            "close",
            "implied_volatility",
            "event_time",
            "ingest_time",
            "sequence",
            "source",
        )
        # The column list is a literal above; no user input reaches it.
        statement = f"COPY option_quotes ({', '.join(columns)}) FROM STDIN"
        with connection.cursor() as cursor, cursor.copy(statement) as copy:
            for row in rows:
                copy.write_row(row)
        return len(rows)

    def write_surface_points(
        self,
        connection: Any,
        rows: Sequence[tuple[Any, ...]],
    ) -> int:
        """Write fitted surface points with the COPY protocol.

        Args:
            connection: An open connection.
            rows: Tuples matching the column order of ``volatility_surfaces``.

        Returns:
            The number of rows written.
        """
        if not rows:
            return 0

        columns = (
            "underlying_symbol",
            "as_of",
            "expiry_epoch_day",
            "strike",
            "implied_volatility",
            "fit_method",
            "rms_error",
            "arbitrage_free",
        )
        statement = _copy_statement("volatility_surfaces", columns)
        with connection.cursor() as cursor, cursor.copy(statement) as copy:
            for row in rows:
                copy.write_row(row)
        return len(rows)

    def write_portfolio_risk(self, connection: Any, row: tuple[Any, ...]) -> int:
        """Write one aggregated portfolio risk row.

        Args:
            connection: An open connection.
            row: Tuple matching the column order of ``portfolio_risk``.

        Returns:
            1 when the row was written, 0 otherwise.
        """
        columns = (
            "portfolio_id",
            "as_of",
            "delta",
            "gamma",
            "vega",
            "theta",
            "rho",
            "gross_notional",
            "net_notional",
        )
        statement = _insert_statement("portfolio_risk", columns)
        with connection.cursor() as cursor:
            cursor.execute(statement, row)
        return 1


def default_ddl_path() -> Path:
    """Path of the checked-in DDL file, for operators who prefer to apply it."""
    return Path(__file__).resolve().parents[3] / "infra" / "timescaledb" / "init.sql"
