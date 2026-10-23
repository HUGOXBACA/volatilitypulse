# ─────────────────────────────────────────────────────────────────────────────
# WebSocket ingestion CLI entry point.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from volpulse_core.clients.kafka import KafkaConfig
from volpulse_core.clients.websocket import WebSocketConfig, run_ingestion
from volpulse_core.clients.websocket.ivolatility import (
    create_ivolatility_websocket_client,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VolPulse WebSocket ingestion")
    parser.add_argument(
        "--uri",
        default=os.environ.get("WS_URI", "wss://api.ivolatility.com/ws/v1"),
        help="WebSocket URI",
    )
    parser.add_argument(
        "--subscriptions",
        default=os.environ.get("WS_SUBSCRIPTIONS", "AAPL,MSFT,SPY"),
        help="Comma-separated list of symbols to subscribe",
    )
    parser.add_argument(
        "--kafka-servers",
        default=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        help="Kafka bootstrap servers",
    )
    parser.add_argument(
        "--kafka-topic",
        default=os.environ.get("KAFKA_TOPIC", "options.chain.streaming"),
        help="Kafka topic for quotes",
    )
    parser.add_argument(
        "--kafka-client-id",
        default=os.environ.get("KAFKA_CLIENT_ID", "volpulse-ingestion"),
        help="Kafka client ID",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to .env file",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    logging.getLogger().setLevel(args.log_level)

    # Load environment
    if args.env_file.exists():
        load_dotenv(args.env_file)
        logger.info("Loaded environment from %s", args.env_file)

    api_key = os.environ.get("IVOL_API_KEY") or os.environ.get("WS_API_KEY")
    if not api_key:
        logger.error("API key not found. Set IVOL_API_KEY or WS_API_KEY in environment or .env")
        return 1

    subscriptions = [s.strip() for s in args.subscriptions.split(",") if s.strip()]

    # Configure Kafka
    kafka_config = KafkaConfig(
        bootstrap_servers=args.kafka_servers,
        client_id=args.kafka_client_id,
    )

    # Configure WebSocket
    ws_config = WebSocketConfig(
        uri=args.uri,
        api_key=api_key,
        subscriptions=subscriptions,
        kafka_config=kafka_config,
        kafka_topic=args.kafka_topic,
    )

    # Create client
    client = create_ivolatility_websocket_client(
        api_key=api_key,
        subscriptions=subscriptions,
        uri=args.uri,
        kafka_config=kafka_config,
    )

    # Handle shutdown signals
    shutdown = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    logger.info("Starting WebSocket ingestion for %s", subscriptions)
    logger.info("Kafka: %s -> %s", args.kafka_servers, args.kafka_topic)

    try:
        stats = await run_ingestion(ws_config, handler=client._handler, shutdown_signal=shutdown)
        logger.info("Ingestion stopped. Stats: %s", stats)
        return 0
    except Exception:
        logger.exception("Ingestion failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))