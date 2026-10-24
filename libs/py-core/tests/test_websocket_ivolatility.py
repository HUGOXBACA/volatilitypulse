# ─────────────────────────────────────────────────────────────────────────────
# Tests for IVolatility WebSocket client.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
from typing import Any

import pytest

from volpulse_core.clients.kafka import KafkaConfig
from volpulse_core.clients.websocket import WebSocketConfig
from volpulse_core.clients.websocket.ivolatility import IVolatilityWebSocketClient
from volpulse_core.models.quote import OptionRight, QuoteSource


class TestIVolatilityWebSocketClient:
    """Tests for IVolatility WebSocket message parsing."""

    @pytest.fixture
    def config(self) -> WebSocketConfig:
        return WebSocketConfig(
            uri="wss://test.example.com/ws",
            api_key="test-key",
            subscriptions=["AAPL", "MSFT"],
            kafka_config=KafkaConfig(),
        )

    @pytest.fixture
    def client(self, config: WebSocketConfig) -> IVolatilityWebSocketClient:
        return IVolatilityWebSocketClient(config)

    # ── Quote parsing tests ───────────────────────────────────────────────────

    def test_parse_quote_basic(self, client: IVolatilityWebSocketClient) -> None:
        """Parse a basic quote message."""
        msg: dict[str, Any] = {
            "type": "quote",
            "data": {
                "symbol": "AAPL240119C00150000",
                "underlying": "AAPL",
                "expiry": "2024-01-19",
                "strike": 150.0,
                "right": "CALL",
                "bid": 1.25,
                "ask": 1.30,
                "last": 1.27,
                "close": 1.20,
                "iv": 0.25,
                "timestamp": 1705680000000000000,
                "sequence": 12345,
            }
        }

        data: dict[str, Any] = msg["data"]
        quotes = client._parse_quote(data)

        assert len(quotes) == 1
        q = quotes[0]
        assert q.contract_id == "AAPL240119C00150000"
        assert q.underlying_symbol == "AAPL"
        assert q.expiry_epoch_day == 19741  # 2024-01-19 in epoch days
        assert q.strike == 150.0
        assert q.right == OptionRight.CALL
        assert q.bid == 1.25
        assert q.ask == 1.30
        assert q.last == 1.27
        assert q.close == 1.20
        assert q.implied_volatility == 0.25
        assert q.event_time_ns == 1705680000000000000
        assert q.sequence == 12345
        assert q.source == QuoteSource.REALTIME_FEED

    def test_parse_quote_put_right(self, client: IVolatilityWebSocketClient) -> None:
        """Parse quote with PUT right."""
        msg: dict[str, Any] = {
            "type": "quote",
            "data": {
                "symbol": "AAPL240119P00150000",
                "underlying": "AAPL",
                "expiry": "2024-01-19",
                "strike": 150.0,
                "right": "PUT",
                "bid": 2.50,
                "ask": 2.60,
                "last": 2.55,
                "close": 2.40,
                "iv": 0.28,
                "timestamp": 1705680000000000000,
                "sequence": 12346,
            }
        }

        data: dict[str, Any] = msg["data"]
        quotes = client._parse_quote(data)

        assert len(quotes) == 1
        q = quotes[0]
        assert q.right == OptionRight.PUT

    def test_parse_quote_various_expiry_formats(self, client: IVolatilityWebSocketClient) -> None:
        """Parse quotes with various expiry date formats."""
        formats = [
            ("2024-01-19", 19741),      # ISO
            ("01/19/2024", 19741),      # MM/DD/YYYY
            ("19-Jan-2024", 19741),     # DD-Mon-YYYY
        ]

        for expiry_str, expected_day in formats:
            msg: dict[str, Any] = {
                "type": "quote",
                "data": {
                    "symbol": f"TEST{expected_day}C00150000",
                    "underlying": "TEST",
                    "expiry": expiry_str,
                    "strike": 150.0,
                    "right": "CALL",
                    "bid": 1.0,
                    "ask": 1.1,
                    "last": 1.05,
                    "close": 1.0,
                    "iv": 0.25,
                    "timestamp": 1705680000000000000,
                    "sequence": 1,
                }
            }
            data: dict[str, Any] = msg["data"]
            quotes = client._parse_quote(data)
            assert quotes[0].expiry_epoch_day == expected_day

    def test_parse_quote_missing_optional_fields(self, client: IVolatilityWebSocketClient) -> None:
        """Parse quote with minimal required fields."""
        msg: dict[str, Any] = {
            "type": "quote",
            "data": {
                "symbol": "AAPL240119C00150000",
                "underlying": "AAPL",
                "expiry": "2024-01-19",
                "strike": 150.0,
                "right": "CALL",
            }
        }

        data: dict[str, Any] = msg["data"]
        quotes = client._parse_quote(data)

        assert len(quotes) == 1
        q = quotes[0]
        assert q.bid == 0.0
        assert q.ask == 0.0
        assert q.last == 0.0
        assert q.close == 0.0
        assert q.implied_volatility == 0.0

    # ── Message type handling tests ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_parse_message_quote_type(self, client: IVolatilityWebSocketClient) -> None:
        """Parse full message with type=quote."""
        msg: dict[str, Any] = {
            "type": "quote",
            "data": {
                "symbol": "AAPL240119C00150000",
                "underlying": "AAPL",
                "expiry": "2024-01-19",
                "strike": 150.0,
                "right": "CALL",
                "bid": 1.25,
                "ask": 1.30,
                "last": 1.27,
                "close": 1.20,
                "iv": 0.25,
                "timestamp": 1705680000000000000,
                "sequence": 12345,
            }
        }

        quotes = await client._parse_message(json.dumps(msg))

        assert len(quotes) == 1
        assert quotes[0].contract_id == "AAPL240119C00150000"

    @pytest.mark.asyncio
    async def test_parse_message_snapshot_type(self, client: IVolatilityWebSocketClient) -> None:
        """Parse full message with type=snapshot (multiple quotes)."""
        msg: dict[str, Any] = {
            "type": "snapshot",
            "data": {
                "quotes": [
                    {
                        "symbol": "AAPL240119C00150000",
                        "underlying": "AAPL",
                        "expiry": "2024-01-19",
                        "strike": 150.0,
                        "right": "CALL",
                        "bid": 1.25,
                        "ask": 1.30,
                        "last": 1.27,
                        "close": 1.20,
                        "iv": 0.25,
                        "timestamp": 1705680000000000000,
                        "sequence": 12345,
                    },
                    {
                        "symbol": "AAPL240119C00160000",
                        "underlying": "AAPL",
                        "expiry": "2024-01-19",
                        "strike": 160.0,
                        "right": "CALL",
                        "bid": 0.85,
                        "ask": 0.90,
                        "last": 0.87,
                        "close": 0.80,
                        "iv": 0.23,
                        "timestamp": 1705680000000000000,
                        "sequence": 12346,
                    },
                ]
            }
        }

        quotes = await client._parse_message(json.dumps(msg))

        assert len(quotes) == 2
        assert quotes[0].strike == 150.0
        assert quotes[1].strike == 160.0

    @pytest.mark.asyncio
    async def test_parse_message_heartbeat(self, client: IVolatilityWebSocketClient) -> None:
        """Heartbeat/ping messages should return empty list."""
        for msg_type in ["heartbeat", "ping"]:
            msg: dict[str, Any] = {"type": msg_type}
            quotes = await client._parse_message(json.dumps(msg))
            assert quotes == []

    @pytest.mark.asyncio
    async def test_parse_message_error(self, client: IVolatilityWebSocketClient) -> None:
        """Error messages should raise ValueError."""
        msg: dict[str, Any] = {"type": "error", "message": "Rate limit exceeded"}

        with pytest.raises(ValueError, match="Rate limit exceeded"):
            await client._parse_message(json.dumps(msg))

    @pytest.mark.asyncio
    async def test_parse_message_unknown_type(self, client: IVolatilityWebSocketClient) -> None:
        """Unknown message types should return empty list and log debug."""
        msg: dict[str, Any] = {"type": "unknown_type", "data": {}}
        quotes = await client._parse_message(json.dumps(msg))
        assert quotes == []

    @pytest.mark.asyncio
    async def test_parse_message_bytes(self, client: IVolatilityWebSocketClient) -> None:
        """Message as bytes should be decoded."""
        msg: dict[str, Any] = {
            "type": "quote",
            "data": {
                "symbol": "AAPL240119C00150000",
                "underlying": "AAPL",
                "expiry": "2024-01-19",
                "strike": 150.0,
                "right": "CALL",
                "bid": 1.25,
                "ask": 1.30,
                "last": 1.27,
                "close": 1.20,
                "iv": 0.25,
                "timestamp": 1705680000000000000,
                "sequence": 12345,
            }
        }

        quotes = await client._parse_message(json.dumps(msg).encode("utf-8"))
        assert len(quotes) == 1

    @pytest.mark.asyncio
    async def test_parse_invalid_json(self, client: IVolatilityWebSocketClient) -> None:
        """Invalid JSON should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            await client._parse_message(b"not valid json")

    # ── Expiry parsing edge cases ─────────────────────────────────────────────

    def test_parse_expiry_to_epoch_day_iso(self, client: IVolatilityWebSocketClient) -> None:
        """ISO format expiry parsing."""
        assert client._parse_expiry_to_epoch_day("2024-01-19") == 19741
        assert client._parse_expiry_to_epoch_day("2024-01-19T00:00:00") == 19741

    def test_parse_expiry_to_epoch_day_us_format(self, client: IVolatilityWebSocketClient) -> None:
        """US date format parsing."""
        assert client._parse_expiry_to_epoch_day("01/19/2024") == 19741

    def test_parse_expiry_to_epoch_day_abbreviated(self, client: IVolatilityWebSocketClient) -> None:
        """Abbreviated month format parsing."""
        assert client._parse_expiry_to_epoch_day("19-Jan-2024") == 19741

    def test_parse_expiry_to_epoch_day_invalid(self, client: IVolatilityWebSocketClient) -> None:
        """Invalid expiry format should raise ValueError."""
        with pytest.raises(ValueError, match="Unrecognized expiry format"):
            client._parse_expiry_to_epoch_day("invalid-date")


# ── Integration test with mocked WebSocket ────────────────────────────────────

class TestIVolatilityWebSocketClientIntegration:
    """Integration tests using mocked WebSocket."""

    @pytest.fixture
    def config(self) -> WebSocketConfig:
        return WebSocketConfig(
            uri="wss://test.example.com/ws",
            api_key="test-key",
            subscriptions=["AAPL"],
            kafka_config=KafkaConfig(),
        )

    @pytest.mark.asyncio
    async def test_client_initialization(self, config: WebSocketConfig) -> None:
        """Test client can be created and configured."""
        client = IVolatilityWebSocketClient(config)
        assert client._config.uri == "wss://test.example.com/ws"
        assert client._config.api_key == "test-key"
        assert client._config.subscriptions == ["AAPL"]

    @pytest.mark.asyncio
    async def test_factory_function(self) -> None:
        """Test factory function creates client correctly."""
        from volpulse_core.clients.websocket.ivolatility import (
            create_ivolatility_websocket_client,
        )

        client = create_ivolatility_websocket_client(
            api_key="test-key",
            subscriptions=["AAPL", "MSFT"],
        )

        assert client._config.api_key == "test-key"
        assert client._config.subscriptions == ["AAPL", "MSFT"]
        assert client._config.uri == "wss://api.ivolatility.com/ws/v1"