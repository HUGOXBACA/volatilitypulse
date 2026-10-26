# ─────────────────────────────────────────────────────────────────────────────
# Tests for Postgres persistence layer (analytics-py).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from volpulse_analytics.persistence.postgres import (
    PostgresConnection,
    PostgresWriter,
    postgres_ddl,
)


class TestPostgresDDL:
    """Tests for Postgres DDL statements."""

    def test_ddl_contains_positions(self) -> None:
        ddl = " ".join(postgres_ddl)
        assert "positions" in ddl
        assert "contract_id" in ddl
        assert "ON CONFLICT" in ddl  # Upsert logic

    def test_ddl_contains_portfolios(self) -> None:
        ddl = " ".join(postgres_ddl)
        assert "portfolios" in ddl
        assert "portfolio_id" in ddl

    def test_ddl_contains_checkpoints(self) -> None:
        ddl = " ".join(postgres_ddl)
        assert "ingestion_checkpoints" in ddl
        assert "topic" in ddl
        assert "partition" in ddl
        assert "offset" in ddl

    def test_ddl_contains_signals(self) -> None:
        ddl = " ".join(postgres_ddl)
        assert "emitted_signals" in ddl
        assert "signal_id" in ddl
        assert "zscore" in ddl
        assert "emitted_at" in ddl

    def test_ddl_contains_positions_upsert(self) -> None:
        ddl = " ".join(postgres_ddl)
        assert "ON CONFLICT (contract_id) DO UPDATE" in ddl

    def test_ddl_contains_checkpoint_upsert(self) -> None:
        ddl = " ".join(postgres_ddl)
        assert "ON CONFLICT (topic, partition) DO UPDATE" in ddl


class TestPostgresConnection:
    """Tests for PostgresConnection."""

    def test_from_settings(self) -> None:
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

    def test_connection_immutable(self) -> None:
        conn = PostgresConnection(
            host="localhost",
            port=5432,
            database="volpulse_state",
            user="volpulse",
            password="secret",
        )
        # Should be frozen dataclass
        with pytest.raises(Exception):
            conn.host = "other"


class TestPostgresWriter:
    """Tests for PostgresWriter (mocked)."""

    @pytest.fixture
    def connection(self):
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

    def test_upsert_positions_empty(self, writer):
        count = writer.upsert_positions(MagicMock(), [])
        assert count == 0