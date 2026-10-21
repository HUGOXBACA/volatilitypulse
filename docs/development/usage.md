# Usage

How to drive each piece of VolPulse. Every command here is a real entry
point; see [getting-started.md](getting-started.md) for the first-time setup.

---

## The `make` targets

`make help` prints the full catalogue. These are the ones you will use.

### Setup

| Target | What it does |
| --- | --- |
| `make bootstrap` | Install toolchains, dependencies, generated code. |
| `make install-py` / `make install-cpp` | Install one language's dependencies. |
| `make proto` | Regenerate the stubs from `contracts/`. |

### Build and test

| Target | What it does |
| --- | --- |
| `make build` | Build the C++ workspace and byte-compile the Python. |
| `make build-cpp` / `make build-py` | One language only. |
| `make test` | Every test suite. |
| `make test-py` / `make test-cpp` | One language only. |
| `make lint` | ruff, mypy, clang-format, buf. |
| `make format` | Apply the fixes that `lint` would suggest. |

### Run

| Target | What it does |
| --- | --- |
| `make demo` | The offline end-to-end run. No Docker, no API key. |
| `make seed` | Generate a synthetic chain for the replay path. |
| `make inspect-log` | Read a binary audit log. |
| `make run-ingestion` | Run the C++ engine against the checked-in config. |
| `make run-analytics` | Run the Python analytics engine. |
| `make run-stack` | Run both. |
| `make infra-up` / `make infra-down` | Manage the local infrastructure. |
| `make topics` | Create the Kafka topics. |
| `make tree` | Print the repository layout. |

---

## The ingestion engine (C++)

```bash
build/bin/volpulse-ingestion --help
```

| Flag | Meaning | Default |
| --- | --- | --- |
| `--config <path>` | Flat `key = value` configuration file. | — |
| `--symbols <A,B>` | Underlying symbols to poll. | — |
| `--binary-log <path>` | Where the audit log is written. | `var/binary-logs/options.vlog` |
| `--replay <path>` | Replay quotes from a flat NDJSON file. | — |
| `--max-batch <n>` | Quotes per poll. | `512` |
| `--poll-interval <s>` | Idle poll interval. | `1.0` |
| `--dry-run` / `--no-dry-run` | Write to the log or not. | dry-run on |
| `--help` | Usage. | — |

### Offline replay

The reliable way to exercise the engine without the upstream:

```bash
make seed                                   # var/replay/aapl.ndjson
build/bin/volpulse-ingestion \
  --replay var/replay/aapl.ndjson \
  --binary-log var/binary-logs/options.vlog \
  --no-dry-run
```

The replay file is newline-delimited JSON. Each line needs at least
`contract_id` and `underlying_symbol`; `strike`, `bid`, `ask`, `last`,
`implied_volatility` and `timestamp_ns` are read when present.

```json
{"contract_id":"AAPL-30-0000","underlying_symbol":"AAPL","strike":121.88,
 "bid":75.03,"ask":76.55,"last":75.79,"implied_volatility":0.4743,
 "timestamp_ns":1700000000000000000}
```

### Live mode

Live polling needs the upstream client, which is **not implemented yet** —
the engine says so and exits with status 2 rather than pretending. The
pieces that are ready (pacing, pagination, checkpointing) are in
`libs/py-core` and specified in
[`libs/cpp-core/include/volpulse/http/README.md`](../../libs/cpp-core/include/volpulse/http/README.md).

---

## The analytics engine (Python)

```bash
make proto                                  # generate the stubs first
export PYTHONPATH="$PWD/.gen/python:$PWD/libs/py-core/src:$PWD/services/analytics-py/src"
poetry -C services/analytics-py run python -m volpulse_analytics --metrics-port 9100
```

| Flag | Meaning | Default |
| --- | --- | --- |
| `--metrics-port <n>` | Port for the Prometheus endpoint. | `9100` |
| `--no-persist` | Compute but do not write to the databases. | off |

It needs `IVOL_API_KEY` in the environment (it validates the configuration
at startup and refuses to run without it). Metrics are served on
`/metrics`.

### Using the quant library directly

The pricing and surface code is usable on its own, without any service
around it:

```python
import numpy as np
from volpulse_analytics.pricing import black_scholes_greeks, black_scholes_price
from volpulse_analytics.surfaces import fit_svi

# Price a chain and compute the Greeks.
strikes = np.array([90.0, 100.0, 110.0])
price = black_scholes_price(100.0, strikes, 0.25, 0.03, 0.01, 0.20)
greeks = black_scholes_greeks(100.0, strikes, 0.25, 0.03, 0.01, 0.20)
print(f"delta: {greeks['delta']}")

# Fit a volatility surface to observed quotes.
log_moneyness = np.log(strikes / 100.0)
total_variance = np.array([0.055, 0.040, 0.032])
fit = fit_svi(log_moneyness, total_variance)
print(f"rmse={fit.rmse:.6f} butterfly_free={fit.butterfly_free}")
```

---

## The binary audit log

The log is the pipeline's audit trail: everything the engine produced, in
order, with a CRC-32 per record.

```bash
make inspect-log                                    # the default path
make inspect-log LOG=var/binary-logs/options.vlog   # a specific file
python tools/scripts/inspect_log.py <path> --quotes 20
```

```
file        : var/binary-logs/options.vlog
size        : 5,576 bytes
records     : 41
valid bytes : 5,576
tail        : clean
sequence    : 0..40
symbols     : AAPL
strike range: 121.88 .. 253.12
```

A torn tail (a crash mid-append) is reported as `TORN OR CORRUPT`. The
writer heals it on the next open: it truncates the damaged tail and
continues from the last valid record.

The on-disk format is documented in
[`libs/cpp-core/include/volpulse/binarylog/format.h`](../../libs/cpp-core/include/volpulse/binarylog/format.h)
and the payload layout in
[`quote_codec.h`](../../services/ingestion-cpp/include/volpulse/ingestion/quote_codec.h).

---

## The upstream client (Python)

```bash
poetry -C libs/py-core run python -m volpulse_core.clients.ivolatility.fetch_iv_data \
  --symbols AAPL,MSFT --days 30 --output-dir var/artifacts/ivolatility
```

It paces every call to the subscription quota, polls the upstream's
asynchronous job until the download is published, walks the result page by
page, validates each page and checkpoints it to Parquet as it goes, so an
interrupted backfill resumes instead of restarting.

---

## The local infrastructure

```bash
make infra-up      # start everything and wait until it is healthy
make topics        # create the Kafka topics
make infra-logs    # tail the stack
make infra-down    # stop it
make infra-reset   # stop it and delete the volumes
```

| Service | Port | Notes |
| --- | --- | --- |
| Kafka | 9092 | KRaft mode, no ZooKeeper. |
| TimescaleDB | 5432 | The time-series store. |
| PostgreSQL | 5433 | The relational store. |
| Prometheus | 9090 | Scrapes the services, evaluates the alert rules. |
| Grafana | 3000 | `admin` / `admin`. The pipeline dashboard is provisioned. |
| InfluxDB | 8086 | Long-horizon metrics. |
| Sensu | 8080 | Alert dispatch. |
| Artifactory | 8081 | Opt-in: `docker compose --profile artifactory up -d`. |

---

## The contracts

```bash
make proto          # regenerate the stubs into .gen/
make proto-lint     # buf lint + format check
make proto-breaking # compare against main
```

The generated Python stubs live in `.gen/python` and the C++ ones in
`.gen/cpp`. They are gitignored and rebuilt from `contracts/` — never edit
them by hand.

To use them from Python:

```bash
export PYTHONPATH="$PWD/.gen/python:$PWD/libs/py-core/src:$PWD/services/analytics-py/src"
```

---

## Writing code

Before you change something:

1. Read [`AGENTS.md`](../../AGENTS.md) — the engineering standards the code
   is held to.
2. Read [`../architecture/data-flow.md`](../architecture/data-flow.md) if you
   are touching a boundary.
3. If you are changing a decision, write an ADR rather than editing the
   old one.

The loop you will be in:

```bash
make format      # apply the style
make lint        # must be clean
make test        # must pass
git commit
```

CI runs the same gates, so a green local run means a green pipeline.
