#!/usr/bin/env python3
"""Generate a synthetic option chain for the offline replay path.

The replay path exists so that the pipeline can be exercised end to end
without spending upstream quota and without depending on the market being
open. The generated file is flat NDJSON, which is the format the C++
ingestion engine reads.

    python tools/scripts/seed_market_data.py --symbol AAPL --output var/replay/aapl.ndjson
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np


def generate_chain(
    symbol: str,
    spot: float,
    expiry_days: int,
    strikes: int,
    seed: int,
) -> list[dict[str, object]]:
    """Generate a synthetic chain with a plausible volatility smile.

    Args:
        symbol: Underlying symbol.
        spot: Spot price of the underlying.
        expiry_days: Days to expiry.
        strikes: Number of strikes in the chain.
        seed: Random seed, so the output is reproducible.

    Returns:
        One record per contract.
    """
    rng = np.random.default_rng(seed)
    maturity = expiry_days / 365.0
    centre = spot
    strike_span = spot * 0.35

    grid = np.linspace(centre - strike_span, centre + strike_span, strikes)
    records: list[dict[str, object]] = []

    base_vol = 0.22
    skew = -0.35
    curvature = 0.55

    for index, strike in enumerate(grid):
        moneyness = math.log(strike / centre)
        smile = base_vol + skew * moneyness + curvature * moneyness**2
        volatility = float(max(smile, 0.05))

        intrinsic = max(spot - strike, 0.0)
        time_value = spot * volatility * math.sqrt(maturity) * 0.4
        mid = intrinsic + time_value
        half_spread = max(mid * 0.01, 0.01)

        records.append(
            {
                "contract_id": f"{symbol}-{expiry_days}-{index:04d}",
                "underlying_symbol": symbol,
                "strike": round(float(strike), 4),
                "bid": round(max(mid - half_spread, 0.0), 4),
                "ask": round(mid + half_spread, 4),
                "last": round(mid, 4),
                "implied_volatility": round(volatility, 6),
                "timestamp_ns": 1_700_000_000_000_000_000 + index * 1_000_000,
            }
        )

    # A little noise, so the replay data is not suspiciously clean.
    jitter = rng.normal(0.0, 0.002, len(records))
    for record, noise in zip(records, jitter, strict=True):
        record["implied_volatility"] = round(
            max(float(record["implied_volatility"]) + float(noise), 0.01), 6
        )

    return records


def main() -> int:
    """Generate the replay file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--spot", type=float, default=187.5)
    parser.add_argument("--expiry-days", type=int, default=30)
    parser.add_argument("--strikes", type=int, default=41)
    parser.add_argument("--seed", type=int, default=20240101)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("var/replay/aapl.ndjson"),
        help="Destination file.",
    )
    args = parser.parse_args()

    records = generate_chain(
        symbol=args.symbol,
        spot=args.spot,
        expiry_days=args.expiry_days,
        strikes=args.strikes,
        seed=args.seed,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    print(f"wrote {len(records)} quotes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
