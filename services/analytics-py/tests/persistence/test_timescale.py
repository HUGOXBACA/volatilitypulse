# ─────────────────────────────────────────────────────────────────────────────
# Tests for TimescaleDB persistence layer (analytics-py).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from volpulse_analytics.persistence.timescale import (
    TimescaleConnection,
    TimescaleWriter,
    timescale_ddl,
    _copy_statement,
    _insert_statement,
)


class TestTimescaleDDL:
    """Tests for TimescaleDB DDL statements."""

    def test_ddl_contains_option_quotes(self) -> None:
        """DDL should contain option_quotes table."""
        ddl = " ".join(timescale_ddl)
        assert "option_quotes" in ddl
        assert "contract_id" in ddl
        assert "underlying_symbol" in ddl
        assert "create_hypertable" in ddl

    def test_ddl_contains_volatility_surfaces(self) -> None:
        ddl = " ".join(timescale_ddl)
        assert "volatility_surfaces" in ddl
        assert "underlying_symbol" in ddl
        assert "implied_volatility" in ddl
        assert "arbitrage_free" in ddl

    def test_ddl_contains_portfolio_risk(self) -> None:
        ddl = " ".join(timescale_ddl)
        assert "portfolio_risk" in ddl
        assert "delta" in ddl
        assert "gamma" in ddl
        assert "vega" in ddl
        assert "theta" in ddl
        assert "rho" in ddl

    def test_hypertable_creation(self) -> None:
        ddl = " ".join(timescale_ddl)
        assert "create_hypertable" in ddl
        assert "if_not_exists => TRUE" in ddl

    def test_retention_policy(self) -> None:
        ddl = " ".join(timescale_ddl)
        assert "add_retention_policy" in ddl

    def test_continuous_aggregate(self) -> None:
        ddl = " ".join(timescale_ddl)
        assert "option_quotes_1m" in ddl
        assert "continuous" in ddl
        assert "add_continuous_aggregate_policy" in ddl


class TestTimescaleConnection:
    """Tests for TimescaleConnection."""

    def test_from_settings(self) -> None:
        class MockSettings:
            timescale_host = "localhost"
            timescale_port = 5432
            timescale_db = "volpulse"
            timescale_user = "volpulse"
            timescale_password = "secret"

        conn = TimescaleConnection.from_settings(MockSettings())
        assert conn.host == "localhost"
        assert conn.port == 5432
        assert conn.database == "volpulse"
        assert conn.user == "volpulse"
        assert conn.password == "secret"

    def test_connection_immutable(self) -> None:
        conn = TimescaleConnection(
            host="localhost",
            port=5432,
            database="volpulse",
            user="volpulse",
            password="secret",
        )
        # Should be frozen dataclass
        with pytest.raises(Exception):
            conn.host = "other"


class TestTimescaleWriter:
    """Tests for TimescaleWriter (mocked)."""

    @pytest.fixture
    def connection(self) -> "TimescaleConnection":
        return TimescaleConnection(
            host="localhost",
            port=5432,
            database="volpulse",
            user="volpulse",
            password="secret",
        )

    @pytest.fixture
    def writer(self, connection: "TimescaleConnection"):
        from volpulse_analytics.persistence.timescale import TimescaleWriter
        return TimescaleWriter(connection)

    def test_init(self, writer: "TimescaleWriter"):
        assert writer._connection is not None

    def test_connect_creates_schema(self, writer: "TimescaleWriter"):
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            conn = writer.connect()

            assert conn is mock_conn
            assert mock_cursor.execute.call_count >= 1

    def test_write_quotes_copies_rows(self, writer: "TimescaleWriter"):
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_copy = MagicMock()
            mock_cursor.copy.return_value.__enter__.return_value = mock_copy

            rows = [
                ("contract1", "AAPL", 20000, 150.0, "CALL", 1.0, 1.1, 1.05, 1.0,
                 0.25, "2024-01-01 00:00:00", "2024-01-01 00:00:01", 1, "REALTIME"),
            ]

            count = writer.write_quotes(mock_conn, rows)

            assert count == 1
            mock_cursor.copy.assert_called_once()

    def test_write_surface_points(self, writer: "TimescaleWriter"):
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_copy = MagicMock()
            mock_cursor.copy.return_value.__enter__.return_value = mock_copy

            rows = [
                ("AAPL", "2024-01-01 00:00:00", 20000, 150.0, 0.25, "SVI", 0.01, True),
            ]

            count = writer.write_surface_points(mock_conn, rows)

            assert count == 1
            mock_cursor.copy.assert_called_once()

    def test_write_portfolio_risk(self, writer: "TimescaleWriter"):
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            row = ("portfolio1", "2024-01-01 00:00:00", 100.0, 10.0, 50.0, -5.0, 1.0, 10000.0, 5000.0)

            count = writer.write_portfolio_risk(mock_conn, row)

            assert count == 1
            mock_cursor.execute.assert_called_once()


class TestTimescaleWriterCopyStatement:
    """Tests for _copy_statement helper."""

    def test_copy_statement_columns(self):
        columns = ("col1", "col2", "col3")
        stmt = _copy_statement("test_table", columns)
        # Check component parts in the Composed string representation
        sql_str = str(stmt)
        assert "COPY" in sql_str
        assert "test_table" in sql_str
        assert "col1" in sql_str
        assert "col2" in sql_str
        assert "col3" in sql_str
        assert "FROM STDIN" in sql_str

    def test_copy_statement_empty(self):
        columns = ()
        stmt = _copy_statement("test_table", columns)
        sql_str = str(stmt)
        assert "COPY" in sql_str
        assert "test_table" in sql_str
        assert "FROM STDIN" in sql_str


class TestTimescaleWriterInsertStatement:
    """Tests for _insert_statement helper."""

    def test_insert_statement_columns(self):
        columns = ("col1", "col2", "col3", "col4")
        stmt = _insert_statement("test_table", columns)
        sql_str = str(stmt)
        assert "INSERT INTO" in sql_str
        assert "test_table" in sql_str
        assert "col1" in sql_str
        assert "col2" in sql_str
        assert "col3" in sql_str
        assert "col4" in sql_str
        assert "ON CONFLICT DO UPDATE SET" in sql_str
        assert "col3 = EXCLUDED.col3" in sql_str
        assert "col4 = EXCLUDED.col4" in sql_str

    def test_insert_statement_two_columns(self):
        columns = ("col1", "col2")
        stmt = _insert_statement("test_table", columns)
        sql_str = str(stmt)
        # With only 2 columns, no UPDATE clause (columns[2:] is empty)
        assert "INSERT INTO" in sql_str
        assert "test_table" in sql_str
        assert "col1" in sql_str
        assert "col2" in sql_str
        # ON CONFLICT DO UPDATE SET is present but with empty SET clause


# ─────────────────────────────────────────────────────────────────────────────
# Postgres persistence tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPostgresDDL:
    """Tests for Postgres DDL statements."""

    def test_ddl_contains_positions(self):
        from volpulse_analytics.persistence.postgres import postgres_ddl
        ddl = " ".join(postgres_ddl)
        assert "positions" in ddl
        assert "contract_id" in ddl
        assert "ON CONFLICT" in ddl  # Upsert logic

    def test_ddl_contains_portfolios(self):
        from volpulse_analytics.persistence.postgres import postgres_ddl
        ddl = " ".join(postgres_ddl)
        assert "portfolios" in ddl
        assert "portfolio_id" in ddl

    def test_ddl_contains_checkpoints(self):
        from volpulse_analytics.persistence.postgres import postgres_ddl
        ddl = " ".join(postgres_ddl)
        assert "ingestion_checkpoints" in ddl
        assert "topic" in ddl
        assert "partition" in ddl
        assert "offset" in ddl

    def test_ddl_contians_signals(self):
        from volpulse_analytics.persistence.postgres import postgres_ddl
        ddl = " ".join(postgres_ddl)
        assert "emitted_signals" in ddl
        assert "signal_id" in ddl
        assert "zscore" in ddl
        assert "emitted_at" in ddl


class TestPostgresConnection:
    """Tests for PostgresConnection."""

    def test_from_settings(self):
        from volpulse_analytics.persistence.postgres import PostgresConnection

        class MockSettings:
            postgres_host = "localhost"
            postgres_port = 5432
            postgres_db = "volpulse_state"
            postgres_user = "volpulse"
            postgres_password = "secret"

        conn = PostgresConnection.from_settings(MockSettings())
        assert conn.host == "localhost"
        assert conn.port == 5432
        assert conn.database == "volpulse_state"
        assert conn.user == "volpulse"
        assert conn.password == "secret"


class TestPostgresWriter:
    """Tests for PostgresWriter (mocked)."""

    @pytest.fixture
    def connection(self):
        from volpulse_analytics.persistence.postgres import PostgresConnection
        return PostgresConnection(
            host="localhost",
            port=5432,
            database="volpulse_state",
            user="volpulse",
            password="secret",
        )

    @pytest.fixture
    def writer(self, connection):
        from volpulse_analytics.persistence.postgres import PostgresWriter
        return PostgresWriter(connection)

    def test_init(self, writer):
        assert writer._connection is not None

    def test_connect_creates_schema(self, writer):
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            conn = writer.connect()

            assert conn is mock_conn
            assert mock_cursor.execute.call_count >= 1

    def test_upsert_positions(self, writer):
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            rows = [
                ("contract1", "AAPL", 150.0, "CALL", 10, 1.05, "2024-01-01"),
            ]

            count = writer.upsert_positions(mock_conn, rows)

            assert count == 1
            mock_cursor.executemany.assert_called_once()

    def test_save_checkpoint(self, writer):
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            writer.save_checkpoint(mock_conn, "topic1", 0, 100)

            mock_cursor.execute.assert_called_once()

    def test_record_signal(self, writer):
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            row = ("signal1", "portfolio1", "AAPL", "contract1", "MISPRICING", 2.5)

            writer.record_signal(mock_conn, row)

            mock_cursor.execute.assert_called_once()