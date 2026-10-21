"""Benchmarks for the VolPulse analytics engine.

These measure the hot paths that the desk cares about:

* pricing and Greeks per contract,
* implied-volatility inversion per contract,
* surface fit per slice,
* portfolio aggregation per position.

Run with:

    PYTHONPATH=.gen/python:libs/py-core/src:services/analytics-py/src \
      poetry -C . run python services/analytics-py/tests/benchmarks/run_benchmarks.py

Numbers are wall-clock per-operation microseconds at the 50th, 95th and 99th
percentiles, plus the total throughput in ops/second. Percentiles are
computed over warm-up-discarded samples so the JIT / allocator steady state
is measured, not startup.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from volpulse_analytics.pricing import black_scholes_greeks, black_scholes_price
from volpulse_analytics.surfaces import fit_svi

__all__ = ["main"]

SPOT = 100.0
RATE = 0.03
DIV = 0.01
MATURITY = 0.5
VOL = 0.25

# 61 strikes evenly spaced around the forward — a realistic snapshot width.
STRIKES = np.linspace(70.0, 130.0, 61)


@dataclass(frozen=True, slots=True)
class BenchResult:
    name: str
    ops: int
    total_seconds: float
    p50_us: float
    p95_us: float
    p99_us: float
    ops_per_second: float


def bench(name: str, fn: Callable[[], None], ops: int = 10_000, warmup: int = 1_000) -> BenchResult:
    """Time ``fn`` repeated ``ops`` times after ``warmup`` throwaway calls."""

    for _ in range(warmup):
        fn()

    times: list[float] = []
    for _ in range(ops):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)

    times.sort()
    p50 = statistics.quantiles(times, n=100)[49]
    p95 = statistics.quantiles(times, n=100)[94]
    p99 = statistics.quantiles(times, n=100)[98]

    return BenchResult(
        name=name,
        ops=ops,
        total_seconds=sum(times),
        p50_us=p50 * 1e6,
        p95_us=p95 * 1e6,
        p99_us=p99 * 1e6,
        ops_per_second=ops / sum(times),
    )


def bm_price() -> None:
    black_scholes_price(STRIKES, SPOT, MATURITY, RATE, DIV, VOL, is_call=True)


def bm_price_scalar() -> None:
    black_scholes_price(100.0, 100.0, MATURITY, RATE, DIV, VOL, is_call=True)


def bm_greeks() -> None:
    black_scholes_greeks(STRIKES, SPOT, MATURITY, RATE, DIV, VOL, is_call=True)


def bm_greeks_scalar() -> None:
    black_scholes_greeks(100.0, 100.0, MATURITY, RATE, DIV, VOL, is_call=True)


def bm_iv_invert() -> None:
    price = float(black_scholes_price(SPOT, 100.0, MATURITY, RATE, DIV, VOL))
    from volpulse_analytics.pricing import implied_volatility_from_price

    implied_volatility_from_price(price, SPOT, 100.0, MATURITY, RATE, DIV)


def bm_iv_invert_batch() -> None:
    prices = black_scholes_price(STRIKES, SPOT, MATURITY, RATE, DIV, VOL)
    from volpulse_analytics.pricing import implied_volatility_from_price

    implied_volatility_from_price(prices, SPOT, STRIKES, MATURITY, RATE, DIV)


def bm_svi_fit() -> None:
    reference = black_scholes_price(STRIKES, SPOT, MATURITY, RATE, DIV, VOL)
    strikes = STRIKES
    forward = SPOT * np.exp((RATE - DIV) * MATURITY)
    k = np.log(strikes / forward)
    w = reference**2
    fit_svi(k, w)


def bm_svi_fit_small() -> None:
    strikes = np.array([80.0, 90.0, 100.0, 110.0, 120.0])
    reference = black_scholes_price(strikes, SPOT, MATURITY, RATE, DIV, VOL)
    forward = SPOT * np.exp((RATE - DIV) * MATURITY)
    k = np.log(strikes / forward)
    w = reference**2
    fit_svi(k, w)


def bm_portfolio_aggregate() -> None:
    from volpulse_analytics.greeks import aggregate_portfolio_risk

    quantities = np.ones_like(STRIKES)
    aggregate_portfolio_risk(
        spot=STRIKES,
        strike=STRIKES,
        time_to_expiry=np.full_like(STRIKES, MATURITY),
        rate=np.full_like(STRIKES, RATE),
        dividend_yield=np.full_like(STRIKES, DIV),
        volatility=np.full_like(STRIKES, VOL),
        quantity=quantities,
    )


def benchmarks() -> list[BenchResult]:
    return [
        bench("black_scholes_price (61 strikes, vectorised)", bm_price, ops=50_000),
        bench("black_scholes_price (scalar)", bm_price_scalar, ops=100_000),
        bench("black_scholes_greeks (61 strikes, vectorised)", bm_greeks, ops=25_000),
        bench("black_scholes_greeks (scalar)", bm_greeks_scalar, ops=50_000),
        bench("implied_volatility_from_price (scalar)", bm_iv_invert, ops=20_000),
        bench("implied_volatility_from_price (61 strikes)", bm_iv_invert_batch, ops=10_000),
        bench("fit_svi (61-point slice)", bm_svi_fit, ops=2_000),
        bench("fit_svi (5-point slice)", bm_svi_fit_small, ops=10_000),
        bench("aggregate_portfolio_risk (61 positions)", bm_portfolio_aggregate, ops=25_000),
    ]


def main() -> int:
    results = benchmarks()

    print("VolPulse analytics benchmarks")
    print("=" * 72)
    print(f"{'benchmark':48s} {'p50 (us)':>10s} {'p95 (us)':>10s} {'p99 (us)':>10s} {'ops/s':>12s}")
    print("-" * 72)
    for result in results:
        print(
            f"{result.name:48s} {result.p50_us:10.2f} {result.p95_us:10.2f} "
            f"{result.p99_us:10.2f} {result.ops_per_second:12,.0f}"
        )

    print("-" * 72)
    total_ops = sum(r.ops for r in results)
    total_time = sum(r.total_seconds for r in results)
    print(f"{'total':48s} {'':>10s} {'':>10s} {'':>10s} {total_ops / total_time:12,.0f}")

    # Regression gates: fail CI if any hot path gets slower than these.
    # These are deliberately loose — they guard against accidental regressions,
    # not against optimisation headroom.
    gates = {
        # Measured baseline (2026-10-21) * 0.5 — guards against regressions,
        # not against optimisation headroom.
        "black_scholes_price (61 strikes, vectorised)": 45_000,  # ops/s
        "black_scholes_price (scalar)": 60_000,  # ops/s
        "black_scholes_greeks (61 strikes, vectorised)": 25_000,  # ops/s
        "black_scholes_greeks (scalar)": 35_000,  # ops/s
        "implied_volatility_from_price (scalar)": 1_500,  # ops/s
        "implied_volatility_from_price (61 strikes)": 1_000,  # ops/s
        "fit_svi (61-point slice)": 350,  # ops/s
        "fit_svi (5-point slice)": 350,  # ops/s
        "aggregate_portfolio_risk (61 positions)": 15_000,  # ops/s
    }

    failures = 0
    for result in results:
        floor = gates.get(result.name)
        if floor is not None and result.ops_per_second < floor:
            print(f"REGRESSION: {result.name} at {result.ops_per_second:,.0f} ops/s < {floor:,}")
            failures += 1

    if failures:
        print(f"\n{failures} regression gate(s) failed.")
        return 1

    print("\nAll regression gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
