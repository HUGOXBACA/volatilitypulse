# ─────────────────────────────────────────────────────────────────────────────
# Surface fitting CLI entry point.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import aiofiles
from dotenv import load_dotenv

from volpulse_core.models.chain import OptionChainSnapshot
from volpulse_core.surface import (
    SurfaceConfig,
    SurfaceMethod,
    fit_surface,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VolPulse volatility surface fitting")
    parser.add_argument(
        "--method",
        default=os.environ.get("SURFACE_METHOD", "SVI"),
        choices=[m.value for m in SurfaceMethod],
        help="Surface fitting method",
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        help="Path to input snapshots (JSON or Parquet)",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=Path("surface_fit.json"),
        help="Path to output fitted surface",
    )
    parser.add_argument(
        "--min-points",
        type=int,
        default=int(os.environ.get("SURFACE_MIN_POINTS", "5")),
        help="Minimum points required for fitting",
    )
    parser.add_argument(
        "--check-arbitrage",
        action="store_true",
        default=bool(os.environ.get("SURFACE_CHECK_ARBITRAGE", "true").lower() == "true"),
        help="Enable arbitrage checks",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level",
    )
    return parser.parse_args()


def load_snapshots(input_file: Path) -> list[OptionChainSnapshot]:
    """Load snapshots from file."""
    # This is a placeholder - in production would load from Parquet/JSON
    logger.warning("Snapshot loading not implemented - using empty list")
    return []


async def main() -> int:
    args = parse_args()

    logging.getLogger().setLevel(args.log_level)

    env_file = Path(".env")
    if env_file.exists():
        load_dotenv(env_file)
        logger.info("Loaded environment from %s", env_file)

    if not args.input_file or not args.input_file.exists():
        logger.error("Input file required and must exist")
        return 1

    snapshots = load_snapshots(args.input_file)

    if not snapshots:
        logger.error("No valid snapshots loaded")
        return 1

    config = SurfaceConfig(
        method=SurfaceMethod(args.method),
        min_points=args.min_points,
        check_arbitrage=args.check_arbitrage,
    )

    logger.info("Fitting surface with method=%s, snapshots=%d", args.method, len(snapshots))

    try:
        result = fit_surface(snapshots, config=config)

        # Save result
        output = {
            "method": result.method.value,
            "underlying_symbol": result.underlying_symbol,
            "as_of_ns": result.as_of_ns,
            "params": result.params,
            "rms_error": result.rms_error,
            "max_error": result.max_error,
            "arbitrage_free": result.arbitrage_free,
            "calendar_arb_violations": result.calendar_arb_violations,
            "butterfly_arb_violations": result.butterfly_arb_violations,
            "fit_time_ms": result.fit_time_ms,
        }

        async with aiofiles.open(args.output_file, "w") as f:
            await f.write(json.dumps(output, indent=2))

        logger.info("Surface fitted successfully: %s", output)
        logger.info("Result saved to %s", args.output_file)
        return 0
    except Exception:
        logger.exception("Surface fitting failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))