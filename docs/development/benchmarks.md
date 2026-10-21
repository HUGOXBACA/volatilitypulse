# Performance benchmarks

VolPulse benchmarks measure the hot paths that determine whether the
pipeline can keep up with the market. There are two suites:

| Suite | Language | What it measures |
| --- | --- | --- |
| C++ ingestion benchmarks | C++20 | Binary log append/read, quote codec encode/decode |
| Python analytics benchmarks | Python 3.12 | Black-Scholes pricing, Greeks, IV inversion, SVI fit, portfolio aggregation |

Every benchmark runs a warm-up phase before timing, so the numbers reflect
steady-state performance, not startup cost. Percentiles are computed over
the warm-up-discarded samples.

## Running

```bash
make bench
```

This runs both suites and checks each result against a regression gate. A
gate failure exits non-zero — it blocks CI.

The C++ suite is also registered as `ctest` target `cpp.benchmarks`; the
Python suite is a standalone script:

```bash
ctest --preset dev -R cpp.benchmarks --output-on-failure
PYTHONPATH=".gen/python:libs/py-core/src:services/analytics-py/src" \
  poetry -C . run python services/analytics-py/tests/benchmarks/run_benchmarks.py
```

---

## Results (2026-10-21)

Measured on an Apple M4 Pro, Python 3.14.3, Clang 21.

### C++ — ingestion engine

| Benchmark | p50 | p95 | p99 | ops/s |
| --- | --- | --- | --- | --- |
| binarylog_append (100 B payload) | 167 ns | 209 ns | 292 ns | 5,212,919 |
| binarylog_append (104 B quote) | 166 ns | 167 ns | 250 ns | 6,207,461 |
| binarylog_read (100 B payload) | 125 ns | 125 ns | 167 ns | 9,400,899 |
| quote_codec_encode | 0 ns | 42 ns | 42 ns | 68,650,789 |
| quote_codec_decode | 0 ns | 42 ns | 42 ns | 52,499,074 |

### Python — analytics engine

| Benchmark | p50 | p95 | p99 | ops/s |
| --- | --- | --- | --- | --- |
| black_scholes_price (61 strikes, vectorised) | 11.0 µs | 11.4 µs | 14.7 µs | 91,825 |
| black_scholes_price (scalar) | 8.4 µs | 8.7 µs | 10.7 µs | 120,239 |
| black_scholes_greeks (61 strikes, vectorised) | 18.4 µs | 18.9 µs | 23.9 µs | 54,911 |
| black_scholes_greeks (scalar) | 13.2 µs | 13.5 µs | 17.0 µs | 76,707 |
| implied_volatility_from_price (scalar) | 316.2 µs | 333.5 µs | 347.8 µs | 3,155 |
| implied_volatility_from_price (61 strikes) | 426.3 µs | 449.2 µs | 464.6 µs | 2,338 |
| fit_svi (61-point slice) | 1,330.3 µs | 1,373.6 µs | 1,413.2 µs | 752 |
| fit_svi (5-point slice) | 1,457.4 µs | 1,573.0 µs | 1,728.3 µs | 684 |
| aggregate_portfolio_risk (61 positions) | 32.5 µs | 35.0 µs | 43.8 µs | 30,502 |

---

## What the numbers mean

### Binary log append (~5–6 M ops/s, ~167 ns p50)

Appending a 100-byte record to the memory-mapped audit log costs about 167
nanoseconds — roughly one cache line of work plus the `memcpy`. At market
rate (tens of thousands of quotes per second across a few dozen symbols)
the log is not the bottleneck; the upstream API quota (one request per
second) is six orders of magnitude slower.

### Quote codec (~50–70 M ops/s, ~42 ns p50)

The fixed-width quote encode/decode is a pure `memcpy` into a packed struct.
Sub-microsecond per record means the codec is invisible in the pipeline.

### Black-Scholes pricing (~90–120 K ops/s)

Pricing a full 61-strike chain takes about 11 µs — that's ~180 ns per
contract. A desk running a few hundred symbols can revalue its entire book
on every snapshot without a Python-level loop.

### Implied volatility inversion (~2–3 K ops/s)

The bisection solver is the most expensive operation: ~430 µs for a
61-strike slice. That's still fast enough to run on every snapshot for a
small book, but a book with thousands of contracts will want the numba/JAX
path described in
[ADR 0004](../adr/0004-accelerator-deferral.md).

### SVI surface fit (~700 ops/s)

Fitting one 61-point slice takes ~1.3 ms. A snapshot with 20 expiries per
symbol spends ~25 ms on surface fitting — fine for a per-minute refresh,
not for sub-second pricing.

---

## Regression gates

Each benchmark has a gate set at 50% of its measured baseline:

| Benchmark | Gate (ops/s) |
| --- | --- |
| binarylog_append (100 B) | 2,000,000 |
| binarylog_append (104 B quote) | 2,000,000 |
| binarylog_read (100 B) | 500,000 |
| quote_codec_encode | 1,000,000 |
| quote_codec_decode | 1,000,000 |
| black_scholes_price (61 strikes) | 45,000 |
| black_scholes_price (scalar) | 60,000 |
| black_scholes_greeks (61 strikes) | 25,000 |
| black_scholes_greeks (scalar) | 35,000 |
| implied_volatility_from_price (scalar) | 1,500 |
| implied_volatility_from_price (61 strikes) | 1,000 |
| fit_svi (61-point slice) | 350 |
| fit_svi (5-point slice) | 350 |
| aggregate_portfolio_risk (61 positions) | 15,000 |

Gates are deliberately loose: they catch accidental regressions (a bad
refactor, a dependency change), not optimisation headroom. When a hot path
is genuinely optimised, update the baseline and the gate together.

---

## Adding a benchmark

1. **C++** — add a timed lambda to
   `services/ingestion-cpp/tests/benchmarks/run_benchmarks.cpp`, register a
   regression gate in the same file, and run `make bench` or
   `ctest -R cpp.benchmarks`.
2. **Python** — add a timed function to
   `services/analytics-py/tests/benchmarks/run_benchmarks.py`, register a
   gate, and run `make bench`.

Benchmarks live next to the unit tests so they're reviewed with the code
they measure.
