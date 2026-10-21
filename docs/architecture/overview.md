# Architecture overview

How the design brief in [`IDEA.md`](../../IDEA.md) maps onto the code.

## Component map

| IDEA.md module | Implementation | Location |
| --- | --- | --- |
| **1. C++ ingestion & structured binary logging** | Feed handler, normaliser, quote codec, memory-mapped binary log | `services/ingestion-cpp/`, `libs/cpp-core/` |
| **2. Distributed messaging layer** | Kafka producer, topic and retention policy | `infra/kafka/`, `contracts/volpulse/options/v1/streaming.proto` |
| **3. Python quant analytics engine** | Consumer, SVI surfaces, Black-Scholes Greeks, mispricing signals | `services/analytics-py/`, `libs/py-core/` |
| **4. High-performance data persistence** | TimescaleDB hypertables for ticks and surfaces, PostgreSQL for state | `infra/timescaledb/`, `infra/postgres/` |
| **5. Observability & incident pipeline** | Prometheus metrics and rules, InfluxDB, Sensu checks | `infra/prometheus/`, `infra/influxdb/`, `infra/sensu/` |
| **Dependency proxy** | Artifactory, behind an opt-in compose profile | `infra/artifactory/` |

## The layering rule

```
contracts/     what both sides agree on          (never contains behaviour)
libs/          what is reusable                   (never contains a process)
services/      what runs                          (may depend on contracts and libs)
infra/         what is deployed alongside          (never imports application code)
```

Dependencies point **downwards only**:

* `services/ingestion-cpp` → `libs/cpp-core` → the standard library.
* `services/analytics-py` → `libs/py-core` (`volpulse_core`) → the standard library.
* `libs/*` never import from `services/*`.
* No module in `libs/` or `services/` reads a file from `infra/`.

The one permitted exception is configuration, which is read from the
environment at the process boundary and passed down explicitly.

## Data flow

A single quote travels like this:

1. **Upstream.** The ingestion engine polls the IVolatility API, paced to the
   subscription quota. The engine owns the pacing: no other component is
   allowed to call the upstream.
2. **Normalisation.** The provider payload is converted into the
   `OptionQuote` protobuf message. Field numbers are frozen; the contract is
   the only thing both sides agree on.
3. **Audit.** The quote is appended to the binary log — memory mapped, CRC-32
   per record, torn tails healed on the next open. The log is what makes the
   pipeline replayable: every Kafka record carries the byte offset of its
   source in the log.
4. **Transport.** The quote is published to Kafka, partitioned by underlying
   symbol so that per-symbol ordering is guaranteed.
5. **Consumption.** The analytics engine consumes the topic, validates the
   payload against the pandera schema, and rejects anything structurally
   impossible before it reaches the quant code.
6. **Computation.** Per expiry, an SVI slice is fitted and checked against
   Lee's butterfly-arbitrage condition. Greeks are computed analytically and
   aggregated over the book.
7. **Persistence.** Quotes, surfaces and risk are written to TimescaleDB
   with `COPY`; positions, checkpoints and emitted signals go to PostgreSQL.
8. **Signals.** Deviations from the model's fair volatility, normalised by
   their historical dispersion, are emitted when they exceed the threshold.
   A signal is recorded so it is never emitted twice.

See [data-flow.md](data-flow.md) for the detail, including the failure
behaviour at every step.

## Cross-cutting concerns

### Time

Every timestamp is UTC and stored as nanoseconds since the Unix epoch on the
wire, and as `timestamptz` in the stores. Expiries are *epoch day* counts
because an expiry is a date, not an instant. There is exactly one clock:
`time.time` in Python, `std::chrono::system_clock` in C++, and the upstream
event time is always preserved next to the ingest time so that latency can
be measured honestly.

### Configuration

Non-secret configuration lives in `config/` and is descriptive. The
authoritative runtime configuration is the environment, read once at process
start by `volpulse_core.config.load_settings()` and passed down explicitly.
No module reads `os.environ` outside that function, and no secret is ever
logged.

### Failure behaviour

| Failure | Behaviour |
| --- | --- |
| Upstream error | Log, back off, retry. Never kill the process. |
| Upstream job never completes | Time out after 300 s and raise. |
| Malformed payload | Drop the record, increment `volpulse_quotes_dropped_total`, continue. |
| Surfaces cannot be fitted | Record the failure, publish no surface, keep the previous one. |
| Surface violates butterfly arbitrage | Publish it flagged `arbitrage_free = false` and never trade it. |
| Database unavailable | Retry with backoff; the broker retains the backlog. |
| Process crash | The binary log self-heals its torn tail; the consumer resumes from its checkpoint. |

### Performance rules

* No Python loop over positions, contracts or ticks. Vectorise with NumPy or
  Polars; the book is revalued as an array operation.
* The binary log is written with `memcpy` into a memory-mapped window, never
  with a syscall per record.
* Batch writes use `COPY`, never row-by-row inserts.
* The hot path allocates nothing it does not have to: domain types are
  frozen and slotted.

## Milestones

| Milestone | Contents | State |
| --- | --- | --- |
| **M1 — Audit trail** | Binary log, quote codec, ingestion run loop, rate limiter, pagination | Done |
| **M2 — Analytics core** | SVI surfaces, butterfly check, Black-Scholes Greeks, portfolio aggregation, signals | Done |
| **M3 — Transport** | Kafka producer, protobuf codegen, consumer wiring, checkpoints | Contracts done, transport pending |
| **M4 — Upstream** | IVolatility REST client, historical backfill, WebSocket feed | Pacing and pagination done, endpoint mapping pending |
| **M5 — Operations** | Prometheus rules, Grafana dashboards, Sensu checks, runbooks | Done |
| **M6 — Acceleration** | numba/JAX kernels, optional CUDA offload | Deliberately deferred, see ADR 0004 |

The order is deliberate: the audit trail comes first because a pipeline you
cannot replay is a pipeline you cannot trust.
