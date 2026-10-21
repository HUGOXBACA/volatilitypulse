# VolPulse

**Institutional-grade options derivative & volatility analytics pipeline.**

VolPulse ingests options chains from the **IVolatility API**, normalises them
in a **C++** engine, records them in a zero-copy **binary audit log**,
publishes them through **Kafka**, and computes real-time **implied volatility
surfaces** and **portfolio Greeks** in **Python** — persisting everything to
**TimescaleDB** and **PostgreSQL**, with **Prometheus**, **InfluxDB** and
**Sensu** watching the whole thing.

The design brief is in [`IDEA.md`](IDEA.md). The architecture that implements
it is described in [`docs/architecture/overview.md`](docs/architecture/overview.md).

---

## Repository layout

The repository is a **polyglot monorepo**. It is organised by *what a
component is* rather than by *what language it is written in*, because the
question "where does this feature live?" must have exactly one answer.

```
volatilitypulse/
├── contracts/          Protobuf contracts — the source of truth for every
│                       inter-service boundary.
├── services/           Deployable units.
│   ├── ingestion-cpp/  Module 1 + 2: C++ ingestion, normalisation, logging.
│   └── analytics-py/   Module 3: Python quant analytics engine.
├── libs/               Reusable code that is not a service.
│   ├── cpp-core/       C++ binary log, HTTP, transport, utilities.
│   └── py-core/        Python models, schemas, upstream clients, telemetry.
├── infra/              Infrastructure as code: broker, stores, monitoring.
├── config/             Non-secret runtime configuration.
├── docs/               Architecture, ADRs, runbooks, operations, glossary.
├── tools/              Developer tooling: bootstrap, codegen, seeding.
├── tests/              Cross-service integration and end-to-end tests.
└── var/                Runtime state (gitignored: logs, artefacts, data).
```

Three rules govern the layout:

1. **A contract lives in `contracts/`.** Anything both sides of a service
   boundary must agree on is a protobuf message. Field numbers are frozen.
2. **A service is a deployable unit.** `services/` holds things that run as
   processes. Everything reusable goes in `libs/`.
3. **A decision is written down.** Anything with a lasting consequence gets an
   ADR; anything that can page someone gets a runbook.

---

## Quick start

```bash
git clone <this repo> && cd volatilitypulse
bash tools/scripts/bootstrap.sh     # toolchains, dependencies, code generation

cp .env.example .env                # then fill in IVOL_API_KEY

make infra-up                       # Kafka, TimescaleDB, Postgres, Prometheus…
make topics                         # create the Kafka topics
make test                           # every test suite, in every language
make run-stack                      # ingestion + analytics, locally
```

Everything is driven through the `Makefile`:

| Target | What it does |
| --- | --- |
| `make help` | List every target. |
| `make bootstrap` | Install toolchains, dependencies, generated code. |
| `make proto` | Regenerate the stubs from `contracts/`. |
| `make build` | Build the C++ workspace and byte-compile the Python. |
| `make test` | Run the C++ and Python test suites. |
| `make lint` / `make format` | ruff, mypy, clang-format, buf. |
| `make infra-up` / `make infra-down` | Manage the local infrastructure. |
| `make run-ingestion` / `make run-analytics` | Run a single service. |
| `make tree` | Print the repository layout. |

---

## The pipeline

```
  [ IVolatility API ]
          │  REST / WebSocket
          ▼
  [ C++ Ingestion & Normalisation ]      services/ingestion-cpp
          │
          ├──► [ Binary Audit Log ]       libs/cpp-core  (zero-copy, mmap)
          │
          ▼  protobuf
  [ Kafka ]                               infra/kafka
          │
          ▼  consumer group
  [ Python Quant Analytics Engine ]       services/analytics-py
          │
          ├──► [ IV Surfaces & Greeks ]    libs/py-core, pricing, surfaces
          ├──► [ TimescaleDB ]             infra/timescaledb
          ├──► [ PostgreSQL ]              infra/postgres
          └──► [ Prometheus / InfluxDB ]   infra/prometheus, infra/influxdb
                        │
                        ▼
                  [ Sensu ]               infra/sensu
```

---

## Current status

| Module | Status | Notes |
| --- | --- | --- |
| Binary audit log | **Complete** | Memory-mapped writer and reader, CRC-32 per record, torn-tail self-healing, 30 unit checks. |
| Quote codec | **Complete** | Fixed-width, endian-explicit on-disk format. |
| Ingestion pipeline | **Complete** | Source/sink interfaces, run loop, graceful shutdown, 27 unit checks. |
| Rate limiter | **Complete** | Async and blocking variants, concurrency-capped. |
| Upstream pagination | **Complete** | Job polling and page iteration, no network dependency in the core. |
| Black-Scholes + Greeks | **Complete** | Vectorised, property tested against put-call parity. |
| SVI surfaces | **Complete** | Raw SVI fit with Lee's butterfly-arbitrage check. |
| IVolatility REST client | **Skeleton** | Pacing, pagination and checkpointing are in place; the endpoint mapping is not. |
| Kafka producer / gRPC control plane | **Specified** | Contract defined in `contracts/`, implementation pending. |
| CUDA / FPGA acceleration | **Not started** | Deliberately deferred: see [ADR 0004](docs/adr/0004-accelerator-deferral.md). |

Milestones are tracked in [`docs/architecture/overview.md`](docs/architecture/overview.md#milestones).
Nothing in this repository is a placeholder implementation: every module that
is listed as complete is built, tested and exercised by the test suites.

---

## Working in this repository

* Read [`AGENTS.md`](AGENTS.md) — it holds the engineering standards that the
  code is held to (typing, linting, validation, performance rules).
* Read [`docs/development/local-setup.md`](docs/development/local-setup.md)
  before your first change.
* Every architectural decision has an ADR in
  [`docs/adr/`](docs/adr/). If you disagree with one, write a new ADR that
  supersedes it — do not edit the old one.
* Every alert has a runbook in [`docs/runbooks/`](docs/runbooks/). If you add
  an alert, you add the runbook in the same change.

## Documentation

| Document | Purpose |
| --- | --- |
| [`IDEA.md`](IDEA.md) | The original design brief. |
| [`docs/architecture/overview.md`](docs/architecture/overview.md) | Component map: brief to code. |
| [`docs/architecture/data-flow.md`](docs/architecture/data-flow.md) | How a quote travels through the system. |
| [`docs/adr/`](docs/adr/) | Architectural decision records. |
| [`docs/runbooks/`](docs/runbooks/) | What to do when it breaks. |
| [`docs/operations/observability.md`](docs/operations/observability.md) | Metrics, alerts and dashboards. |
| [`docs/glossary.md`](docs/glossary.md) | The vocabulary of the desk. |
