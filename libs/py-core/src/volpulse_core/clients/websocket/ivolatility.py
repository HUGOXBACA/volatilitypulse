# ─────────────────────────────────────────────────────────────────────────────
# IVolatility WebSocket provider implementation.
#
# Implements the IVolatility real-time WebSocket feed parsing.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from volpulse_core.clients.kafka import KafkaConfig
from volpulse_core.clients.websocket import WebSocketClient, WebSocketConfig
from volpulse_core.models.quote import OptionQuote, OptionRight, QuoteSource

logger = logging.getLogger(__name__)


class IVolatilityWebSocketClient(WebSocketClient):
    """IVolatility-specific WebSocket client.

    Message format (based on IVolatility WebSocket API):
    {
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
            "bid_size": 10,
            "ask_size": 5,
            "iv": 0.25,
            "volume": 100,
            "open_interest": 500,
            "timestamp": 1705680000000000000,
            "sequence": 12345
        }
    }
    """

    def __init__(self, config: WebSocketConfig) -> None:
        super().__init__(config, handler=self._handle_quotes)
        self._sequence = 0

    async def _handle_quotes(self, quotes: list[OptionQuote]) -> None:
        """Default handler - publishes to Kafka via parent class."""
        await super()._default_handler(quotes)

    async def _parse_message(self, message: str | bytes) -> list[OptionQuote]:
        """Parse IVolatility WebSocket message to OptionQuote list."""
        if isinstance(message, bytes):
            message = message.decode("utf-8")

        try:
            data = json.loads(message)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e

        # Handle different message types
        msg_type = data.get("type", "")
        if msg_type == "quote":
            return self._parse_quote(data.get("data", {}))
        elif msg_type == "snapshot":
            # Full chain snapshot - multiple quotes
            quotes = []
            for q_data in data.get("data", {}).get("quotes", []):
                quotes.extend(self._parse_quote(q_data))
            return quotes
        elif msg_type == "heartbeat" or msg_type == "ping":
            # Ignore heartbeats
            return []
        elif msg_type == "error":
            raise ValueError(f"Provider error: {data.get('message', 'Unknown error')}")
        else:
            logger.debug("Unknown message type: %s", msg_type)
            return []

    def _parse_quote(self, q: dict[str, Any]) -> list[OptionQuote]:
        """Parse single quote data dict to OptionQuote."""
        try:
            # Parse expiry to epoch day
            expiry_str = q.get("expiry", "")
            expiry_epoch_day = self._parse_expiry_to_epoch_day(expiry_str)

            # Parse right
            right_str = q.get("right", "").upper()
            right = OptionRight.CALL if right_str == "CALL" else OptionRight.PUT

            # Timestamps
            event_time_ns = q.get("timestamp", int(time.time() * 1_000_000_000))
            ingest_time_ns = int(time.time() * 1_000_000_000)

            # Sequence number
            self._sequence += 1
            sequence = q.get("sequence", self._sequence)

            quote = OptionQuote(
                contract_id=q.get("symbol", ""),
                underlying_symbol=q.get("underlying", ""),
                expiry_epoch_day=expiry_epoch_day,
                strike=float(q.get("strike", 0.0)),
                right=right,
                bid=float(q.get("bid", 0.0)),
                ask=float(q.get("ask", 0.0)),
                last=float(q.get("last", 0.0)),
                close=float(q.get("close", 0.0)),
                implied_volatility=float(q.get("iv", 0.0)),
                event_time_ns=event_time_ns,
                ingest_time_ns=ingest_time_ns,
                sequence=sequence,
                source=QuoteSource.REALTIME_FEED,
            )
            return [quote]

        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(f"Failed to parse quote: {e}") from e

    def _parse_expiry_to_epoch_day(self, expiry_str: str) -> int:
        """Convert expiry string to epoch day count."""
        try:
            # Try ISO format first
            dt = datetime.fromisoformat(expiry_str)
        except ValueError:
            # Try common formats
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"):
                try:
                    dt = datetime.strptime(expiry_str, fmt).replace(tzinfo=UTC)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Unrecognized expiry format: {expiry_str}")

        return int(dt.timestamp() // 86400)


# ─── Factory function ────────────────────────────────────────────────────────


def create_ivolatility_websocket_client(
    api_key: str,
    subscriptions: list[str],
    uri: str = "wss://api.ivolatility.com/ws/v1",
    kafka_config: KafkaConfig | None = None,
    **kwargs: Any,
) -> IVolatilityWebSocketClient:
    """Create configured IVolatility WebSocket client."""
    config = WebSocketConfig(
        uri=uri,
        api_key=api_key,
        subscriptions=subscriptions,
        kafka_config=kafka_config or KafkaConfig(),
        **kwargs,
    )
    return IVolatilityWebSocketClient(config)