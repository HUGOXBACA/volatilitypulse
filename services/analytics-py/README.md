# `volpulse-analytics` — the Python quant analytics engine

The service that consumes normalised quotes and produces the products the
desk cares about: implied volatility surfaces, portfolio Greeks and
mispricing signals.

Module 3 of the design brief, plus the persistence and observability parts
of Modules 4 and 5.

## Layout

```
src/volpulse_analytics/
├── main.py                  Entry point: config, metrics, consumer loop.
├── consumer.py              Decode, validate, fit, persist.
├── pricing/
│   └── black_scholes.py     Vectorised pricing and analytic Greeks.
├── greeks/
│   └── portfolio.py         Aggregation of position risk.
├── surfaces/
│   └── svi.py               Raw SVI fitting and the arbitrage check.
├── signals/
│   └── mispricing.py        Z-scored deviations from the model's fair value.
└── persistence/
    ├── timescale.py         Ticks, surfaces and risk.
    └── postgres.py          Positions, checkpoints, emitted signals.
```

## The pipeline of one record

```
broker record
  → protobuf envelope
  → DecodedQuote
  → group by expiry
  → SVI fit per slice
  → Lee's butterfly-arbitrage check
  → Greeks and portfolio risk
  → TimescaleDB / PostgreSQL
  → metrics
  → commit the offset
```

The decoder is injected rather than imported, so the consumer can be tested
without a broker and without generated stubs.

## The numerical rules

* **Vectorise.** A snapshot is an array operation. There is no Python-level
  loop over quotes or positions.
* **Implied volatility by bisection.** The solver cannot diverge: each
  element is solved independently, and a price outside the no-arbitrage
  bounds returns `NaN` rather than a plausible-looking wrong number.
* **Greeks analytically.** Delta, gamma, vega, theta and rho come from the
  closed forms, not from finite differences.
* **Check the surface before you use it.** A slice whose implied density
  goes negative allows a butterfly arbitrage. It is published with
  `arbitrage_free = false` and never traded on.
* **Property-test the maths.** Put-call parity, the no-arbitrage bounds and
  the implied volatility round trip are checked with `hypothesis`, over
  hundreds of generated cases.

## Running

```bash
make infra-up
make topics
poetry -C services/analytics-py run python -m volpulse_analytics
```

The generated protobuf stubs must be on the path:

```bash
make proto
export PYTHONPATH="$PWD/.gen/python:$PYTHONPATH"
```

Metrics are served on `:9100/metrics`.

## Tests

```bash
poetry -C pyproject.toml run pytest services/analytics-py/tests -v
```

| File | What it checks |
| --- | --- |
| `test_black_scholes.py` | Put-call parity, price bounds, the implied volatility round trip, the shape of the Greeks. |
| `test_svi.py` | Parameter recovery, the input validation, the butterfly and calendar arbitrage checks. |
| `test_portfolio.py` | Aggregation: hedging, sign conventions, the contract multiplier. |
