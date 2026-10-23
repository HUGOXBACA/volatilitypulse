# ─────────────────────────────────────────────────────────────────────────────
# Ingestion control server CLI entry point.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys

from volpulse_core.control.server import run_control_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VolPulse ingestion control server")
    parser.add_argument(
        "--host",
        default=os.environ.get("GRPC_HOST", "[::]"),
        help="Host to bind to",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("GRPC_PORT", "50051")),
        help="Port to listen on",
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

    logger.info("Starting control server on %s:%d", args.host, args.port)

    try:
        await run_control_server(args.host, args.port, shutdown_event=shutdown)
        return 0
    except Exception:
        logger.exception("Control server failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))