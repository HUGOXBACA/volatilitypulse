# `volpulse_core` — shared Python library

The reusable half of the Python stack. It contains no process, no service
entrypoint and no dependency on the analytics engine. The analytics service
in `services/analytics-py` depends on it; it never depends on the service.

## Why a separate distribution

The ingestion tooling, the backfill scripts and the dashboards all need the
domain types and the upstream clients, and none of them need the analytics
stack. Splitting the library out keeps the analytics dependencies
(`confluent-kafka`, `scipy`, `psycopg`) out of a backfill job that only
needs `httpx` and `polars`.

## Layout

```
src/volpulse_core/
├── config.py                     Settings, read once from the environment.
├── models/                       Frozen, slotted domain types.
│   ├── quote.py                  OptionQuote — the atom of the pipeline.
│   └── chain.py                  OptionChainSnapshot, PortfolioPosition.
├── schemas/                      pandera validation of upstream payloads.
│   └── option_quote.py
├── clients/
│   └── ivolatility/
│       ├── rate_limit.py         Pacing. The upstream quota lives here.
│       ├── pagination.py         Job polling and page iteration.
│       └── fetch_iv_data.py      Historical backfill with checkpointing.
├── io/
│   └── parquet.py                Atomic Parquet and NPZ writes.
└── observability/
    └── metrics.py                The metric set. Names are a contract.
```

## Rules

* **Frozen and slotted.** Domain types are created on the hot path. They are
  immutable, they allocate no dictionary, and they compare and hash by
  value.
* **No `os.environ` outside `config.py`.** Configuration is read once, at
  the process boundary, and passed down explicitly.
* **Validation at the edge.** Anything that arrives from outside is
  validated against a pandera schema before it reaches the quant code.
* **Vectorise.** No Python-level loop over quotes, contracts or positions.
* **No secrets in logs.** The redaction list in `config/logging.yaml` is
  binding.

## Installation

The package is installed from the monorepo root:

```bash
poetry -C libs/py-core install
```

or, from the service, as a path dependency:

```toml
volpulse-core = { path = "../../libs/py-core", develop = true }
```

## Tests

```bash
poetry -C pyproject.toml run pytest libs/py-core/tests -v
```

The suite covers the properties that matter: the limiter must space calls
and must never leak a slot; the pagination helpers must not block the event
loop and must not loop forever; the models must reject structurally
impossible quotes.
