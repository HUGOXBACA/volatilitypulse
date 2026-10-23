# ─────────────────────────────────────────────────────────────────────────────
# WebSocket ingestion client for VolPulse.
#
# Provides async WebSocket connections to real-time options data feeds with
# automatic reconnection, backpressure handling, and protobuf serialization
# to the Kafka message bus.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed, WebSocketException

from volpulse_core.clients.kafka import KafkaConfig, KafkaProducer
from volpulse_core.models.quote import OptionQuote

logger = logging.getLogger(__name__)

__all__ = [
    "WebSocketClient",
    "WebSocketConfig",
    "WebSocketMessageHandler",
    "run_ingestion",
]

# ── Configuration ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class WebSocketConfig:
    """Configuration for WebSocket ingestion client."""

    uri: str
    api_key: str
    subscriptions: list[str]
    ping_interval: float = 20.0
    ping_timeout: float = 10.0
    max_reconnect_attempts: int = 10
    base_reconnect_delay: float = 1.0
    max_reconnect_delay: float = 60.0
    backpressure_limit: int = 10000
    kafka_config: KafkaConfig | None = None
    kafka_topic: str = "options.chain.streaming"


# ── Message Handler Protocol ──────────────────────────────────────────────────


class WebSocketMessageHandler(Protocol):
    """Protocol for handling parsed WebSocket messages."""

    async def __call__(self, quotes: list[OptionQuote]) -> None: ...


# ── Internal State ────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _ConnectionState:
    """Mutable connection state."""

    connected: bool = False
    reconnect_attempts: int = 0
    last_message_time: float = 0.0
    messages_received: int = 0
    messages_processed: int = 0
    messages_failed: int = 0
    backpressure_drops: int = 0


# ── WebSocket Client ──────────────────────────────────────────────────────────


class WebSocketClient:
    """Async WebSocket client for real-time options data ingestion.

    Features:
    - Automatic reconnection with exponential backoff
    - Per-connection message queue with backpressure
    - Protobuf serialization to Kafka
    - Health monitoring and metrics
    """

    __slots__ = (
        "_config",
        "_handler",
        "_producer",
        "_queue",
        "_shutdown_event",
        "_state",
        "_tasks",
        "_ws",
    )

    def __init__(
        self,
        config: WebSocketConfig,
        handler: WebSocketMessageHandler | None = None,
    ) -> None:
        self._config = config
        self._handler = handler or self._default_handler
        self._state = _ConnectionState()
        self._ws: ClientConnection | None = None
        self._queue: asyncio.Queue[list[OptionQuote]] = asyncio.Queue(
            maxsize=config.backpressure_limit
        )
        self._producer: KafkaProducer | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._shutdown_event = asyncio.Event()

    async def _default_handler(self, quotes: list[OptionQuote]) -> None:
        """Default handler publishes to Kafka."""
        if self._producer is not None and quotes:
            try:
                self._producer.produce(quotes)
            except (RuntimeError, ValueError, OSError) as e:
                logger.error("Failed to publish quotes to Kafka: %s", e)
                self._state.messages_failed += len(quotes)

    async def connect(self) -> None:
        """Establish WebSocket connection and initialize Kafka producer."""
        self._producer = KafkaProducer(
            self._config.kafka_config,
            topic=self._config.kafka_topic,
        )

        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        self._ws = await websockets.connect(
            self._config.uri,
            additional_headers=headers,
            ping_interval=self._config.ping_interval,
            ping_timeout=self._config.ping_timeout,
            max_size=2**20,  # 1 MB max message
        )

        # Send subscription message
        sub_msg = {
            "action": "subscribe",
            "symbols": self._config.subscriptions,
        }
        await self._ws.send(str(sub_msg))

        self._state.connected = True
        self._state.reconnect_attempts = 0
        logger.info("WebSocket connected to %s", self._config.uri)

    async def disconnect(self) -> None:
        """Gracefully close connections."""
        self._shutdown_event.set()

        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        if self._ws is not None:
            await self._ws.close()
            self._ws = None

        if self._producer is not None:
            self._producer.close()
            self._producer = None

        self._state.connected = False
        logger.info("WebSocket disconnected")

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        while (
            self._state.reconnect_attempts < self._config.max_reconnect_attempts
            and not self._shutdown_event.is_set()
        ):
            delay = min(
                self._config.base_reconnect_delay * (2**self._state.reconnect_attempts),
                self._config.max_reconnect_delay,
            )
            logger.warning(
                "Reconnecting in %.1fs (attempt %d/%d)",
                delay,
                self._state.reconnect_attempts + 1,
                self._config.max_reconnect_attempts,
            )
            await asyncio.sleep(delay)
            self._state.reconnect_attempts += 1

            try:
                await self.connect()
                return
            except (ConnectionClosed, WebSocketException, OSError) as e:
                logger.error("Reconnect attempt %d failed: %s", self._state.reconnect_attempts, e)

        logger.error("Max reconnect attempts reached, giving up")
        self._shutdown_event.set()

    async def _reader(self) -> None:
        """Read messages from WebSocket and parse to quotes."""
        if self._ws is None:
            return

        try:
            async for message in self._ws:
                if self._shutdown_event.is_set():
                    break

                self._state.last_message_time = time.time()
                self._state.messages_received += 1

                try:
                    quotes = await self._parse_message(message)
                    if quotes:
                        try:
                            self._queue.put_nowait(quotes)
                        except asyncio.QueueFull:
                            self._state.backpressure_drops += len(quotes)
                            logger.warning(
                                "Backpressure queue full, dropped %d quotes",
                                len(quotes),
                            )
                except (ValueError, TypeError, KeyError) as e:
                    self._state.messages_failed += 1
                    logger.error("Failed to parse message: %s", e)

        except ConnectionClosed as e:
            logger.warning("WebSocket connection closed: %s", e)
        except WebSocketException as e:
            logger.error("WebSocket error: %s", e)
        except (RuntimeError, OSError) as e:
            logger.error("Reader task error: %s", e)
        finally:
            self._state.connected = False
            if not self._shutdown_event.is_set():
                await self._reconnect()

    async def _parse_message(self, message: str | bytes) -> list[OptionQuote]:
        """Parse WebSocket message to OptionQuote list.

        This is a stub - implement based on your provider's message format.
        """
        # TODO: Implement provider-specific parsing
        # Example structure:
        # {
        #   "type": "quote",
        #   "symbol": "AAPL240119C00150000",
        #   "underlying": "AAPL",
        #   "expiry": "2024-01-19",
        #   "strike": 150.0,
        #   "right": "CALL",
        #   "bid": 1.25,
        #   "ask": 1.30,
        #   "last": 1.27,
        #   "close": 1.20,
        #   "iv": 0.25,
        #   "timestamp": 1705680000000000000,
        #   "sequence": 12345
        # }
        raise NotImplementedError("Provider-specific message parsing not implemented")

    async def _processor(self) -> None:
        """Process queued quotes through handler."""
        while not self._shutdown_event.is_set():
            try:
                quotes = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue

            try:
                await self._handler(quotes)
                self._state.messages_processed += len(quotes)
            except (RuntimeError, ValueError, OSError) as e:
                self._state.messages_failed += len(quotes)
                logger.error("Handler failed: %s", e)
            finally:
                self._queue.task_done()

    async def run(self) -> None:
        """Run the ingestion loop until shutdown."""
        await self.connect()

        self._tasks = [
            asyncio.create_task(self._reader()),
            asyncio.create_task(self._processor()),
        ]

        try:
            await self._shutdown_event.wait()
        finally:
            await self.disconnect()

    def get_stats(self) -> dict[str, Any]:
        """Return current client statistics."""
        return {
            "connected": self._state.connected,
            "reconnect_attempts": self._state.reconnect_attempts,
            "messages_received": self._state.messages_received,
            "messages_processed": self._state.messages_processed,
            "messages_failed": self._state.messages_failed,
            "backpressure_drops": self._state.backpressure_drops,
            "queue_size": self._queue.qsize(),
            "last_message_age_sec": time.time() - self._state.last_message_time
            if self._state.last_message_time
            else None,
        }


# ── Convenience Runner ────────────────────────────────────────────────────────


async def run_ingestion(
    config: WebSocketConfig,
    handler: WebSocketMessageHandler | None = None,
    shutdown_signal: asyncio.Event | None = None,
) -> dict[str, Any]:
    """Run WebSocket ingestion until shutdown signal.

    Args:
        config: WebSocket and Kafka configuration
        handler: Optional custom message handler
        shutdown_signal: Optional external shutdown event

    Returns:
        Final statistics dictionary
    """
    client = WebSocketClient(config, handler)
    shutdown = shutdown_signal or asyncio.Event()

    async def _wait_for_shutdown() -> None:
        await shutdown.wait()
        await client.disconnect()

    await asyncio.gather(client.run(), _wait_for_shutdown())
    return client.get_stats()