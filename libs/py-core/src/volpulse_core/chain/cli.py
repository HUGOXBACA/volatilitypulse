# ─────────────────────────────────────────────────────────────────────────────
# Chain builder CLI entry point.
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

from volpulse_core.chain import ChainBuilderConfig, run_chain_builder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VolPulse chain builder")
    parser.add_argument(
        "--snapshot-interval",
        type=float,
        default=float(os.environ.get("CHAIN_SNAPSHOT_INTERVAL", "1.0")),
        help="Snapshot emission interval in seconds",
    )
    parser.add_argument(
        "--max-buffer-size",
        type=int,
        default=int(os.environ.get("CHAIN_MAX_BUFFER_SIZE", "10000")),
        help="Maximum quotes to buffer before forced emission",
    )
    parser.add_argument(
        "--max-sequence-gap",
        type=int,
        default=int(os.environ.get("CHAIN_MAX_SEQUENCE_GAP", "1000")),
        help="Maximum gap in sequence numbers before warning",
    )
    parser.add_argument(
        "--emit-on-every-quote",
        action="store_true",
        help="Emit snapshot on every quote (for testing)",
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
    env_file = Path(".env")
    if env_file.exists():
        load_dotenv(env_file)
        logger.info("Loaded environment from %s", env_file)

    config = ChainBuilderConfig(
        snapshot_interval=args.snapshot_interval,
        max_buffer_size=args.max_buffer_size,
        max_sequence_gap=args.max_sequence_gap,
        emit_on_every_quote=args.emit_on_every_quote,
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

    logger.info("Starting chain builder with config: %s", config)

    try:
        stats = await run_chain_builder(config, shutdown_signal=shutdown)
        logger.info("Chain builder stopped. Stats: %s", stats)
        return 0
    except Exception:
        logger.exception("Chain builder failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))