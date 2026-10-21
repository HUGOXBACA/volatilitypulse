# Data flow

The life of a single quote, and what happens when each step fails.

## 1. Upstream poll

The ingestion engine polls the IVolatility API for the symbols it is
configured with. Every call goes through a `RateLimiter` configured at one
request per second, which is the subscription quota. The limiter also caps
concurrency so a slow response cannot pile up connections.

**On failure:** the error is logged with its class, the engine backs off by
the poll interval, and it retries. The process never exits because of an
upstream error — process lifetime belongs to the supervisor.

**On a wide query:** the upstream answers with a job rather than with data.
The engine polls the job's details URL until the upstream publishes a
download URL, then walks the result page by page. Each page is validated and
checkpointed to Parquet before the next one is requested, so an interrupted
backfill resumes instead of restarting.

## 2. Normalisation

The provider payload becomes an `OptionQuote`:

| Provider field | Contract field | Normalisation |
| --- | --- | --- |
| contract identifier | `contract_id` | copied verbatim |
| symbol | `underlying_symbol` | upper-cased |
| expiration date | `expiry_epoch_day` | date → epoch day count, UTC |
| strike | `strike` | float, no scaling |
| bid / ask / last / close | `bid`, `ask`, `last`, `close` | float, negative prices rejected |
| implied volatility | `implied_volatility` | decimal, `NaN` when absent |
| event time | `event_time` | `Timestamp`, UTC |
| — | `ingest_time` | stamped by the engine |
| — | `sequence` | monotonic per partition |

The normalised quote is a **flat protobuf message**. It is copied into the
binary log and onto the wire without a transformation in between: one
representation, three consumers, no conversion layer.

## 3. Audit

The quote is appended to the binary log:

```
┌──────────── RecordHeader (32 bytes) ────────────┐
│ magic │ ver │ flags │ size │ sequence │ ts │ crc │
└──────────────────────────────────────────────────┘
┌──────────── payload (104 bytes) ─────────────────┐
└──────────────────────────────────────────────────┘
```

* The header is fixed width and endian-explicit, so a log written on one
  machine decodes on another.
* The CRC-32 covers the payload. A reader that finds a bad CRC stops at that
  record: everything after it is not trustworthy.
* The writer maps the file into memory. Appending is a `memcpy`, not a
  syscall.
* A crash in the middle of an append leaves a torn record. The next writer
  to open the file scans it, truncates the torn tail and continues. The log
  heals itself.

The byte offset of every record is carried in the Kafka envelope
(`binary_log_offset`), so any consumed record can be replayed from disk
without touching the broker.

## 4. Transport

The quote is published to `options.chain.streaming`, partitioned by
`underlying_symbol`. Per-symbol ordering is therefore guaranteed, which is
what makes the surfaces well defined: a snapshot is a set of quotes for one
symbol at one time.

The envelope carries the schema version, the producer identity and epoch,
the production timestamp and the audit-log offset, so the consumer can route,
de-duplicate and replay without consulting the broker metadata.

**Retention:** seven days on the streaming topic, one day on the realtime
topic, thirty days on the dead-letter topic.

## 5. Consumption

The analytics engine joins the consumer group and polls. For each record it:

1. decodes the protobuf envelope,
2. validates the quotes against the pandera schema — a structurally
   impossible payload is dropped here, with a counter, and never reaches the
   quant code,
3. groups the quotes by expiry and fits an SVI slice per slice,
4. checks the slice against Lee's butterfly-arbitrage condition,
5. computes Greeks and portfolio risk,
6. writes to TimescaleDB and PostgreSQL,
7. commits the offset.

The offset is committed **after** the result is durable. The broker retains
the backlog, so a crash costs time, not data.

## 6. Computation

### Surfaces

Per underlying and expiry, the quotes give a set of points in
(log-moneyness, total variance) space. A raw SVI slice is fitted:

```
w(k) = a + b · (ρ(k − m) + √((k − m)² + σ²))
```

The fitter reports the residual error, and the slice is checked against
Lee's moment formula: the density implied by the slice must not go negative,
because a negative density is a butterfly arbitrage. Such a surface is
published with `arbitrage_free = false` and is never traded on.

### Greeks

Delta, gamma, vega, theta and rho come from the closed-form
Black-Scholes-Merton formulas, vectorised over the whole book. Aggregation
over positions is an array operation, not a loop.

### Signals

The deviation of the market's implied volatility from the model's fair
volatility is normalised by the historical dispersion of that deviation.
Only deviations beyond the threshold are actionable. A signal that has been
emitted is recorded in PostgreSQL, so the same contract cannot be alerted on
twice within the cooldown.

## 7. Persistence

| Data | Store | Method |
| --- | --- | --- |
| Normalised quotes | TimescaleDB `option_quotes` | `COPY` into a hypertable |
| Fitted surfaces | TimescaleDB `volatility_surfaces` | `COPY` into a hypertable |
| Portfolio risk | TimescaleDB `portfolio_risk` | `INSERT ... ON CONFLICT DO UPDATE` |
| Positions | PostgreSQL `positions` | `INSERT ... ON CONFLICT DO UPDATE` |
| Consumer offsets | PostgreSQL `ingestion_checkpoints` | `INSERT ... ON CONFLICT DO UPDATE` |
| Emitted signals | PostgreSQL `emitted_signals` | `INSERT ... ON CONFLICT DO NOTHING` |

Writes are atomic: data is written to a temporary file in the destination
directory and renamed into place, so a crash never leaves a half-written
artefact behind.

## 8. Observability

Every step above emits metrics:

| Metric | Meaning |
| --- | --- |
| `volpulse_quotes_consumed_total` | Quotes accepted by the consumer. |
| `volpulse_quotes_dropped_total` | Quotes rejected, by reason. |
| `volpulse_end_to_end_latency_seconds` | Upstream event time to analytics. |
| `volpulse_consumer_lag_seconds` | Age of the oldest record in the partition. |
| `volpulse_surface_fit_rms_error` | Quality of the most recent fit. |
| `volpulse_surface_arbitrage_violations_total` | Static arbitrage detected. |
| `volpulse_upstream_pacing_delay_seconds` | How hard the client is throttled. |

Each alerting rule maps onto a runbook in [`../runbooks/`](../runbooks/).
