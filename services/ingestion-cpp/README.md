# `volpulse-ingestion` — C++ ingestion and normalisation engine

The service that talks to the upstream provider. It is Module 1 and Module 2
of the design brief: it polls the IVolatility API, normalises the payload
into the `OptionQuote` contract, writes the binary audit log and publishes
to the broker.

## Layout

```
include/volpulse/ingestion/
├── config.h          Runtime configuration (flat `key = value` file + flags).
├── pipeline.h        The run loop, and the source/sink interfaces.
├── quote_codec.h     The fixed-width on-disk quote representation.
└── ndjson_source.h   The offline replay source.

src/
├── main.cpp          Entry point and signal handling.
├── config.cpp        Configuration parsing.
├── pipeline.cpp      The run loop, the binary log sink, the null sink.
├── quote_codec.cpp   Encode and decode.
└── ndjson_source.cpp The flat NDJSON reader.

tests/
└── pipeline_test.cpp Configuration, codec and pipeline tests.
```

## The shape of the service

```
QuoteSource ──► Pipeline ──► QuoteSink
```

The pipeline owns the run loop, the pacing, the error handling and the
counters. It knows nothing about HTTP, Kafka or the binary log format:
those arrive through the two interfaces. That is what makes the loop
testable without a network, and it is the seam where the broker transport
will be added.

| Component | Responsibility | State |
| --- | --- | --- |
| `NdjsonQuoteSource` | Replay quotes from a flat NDJSON file. | Complete. |
| `RestQuoteSource` | Poll the upstream, paced, with pagination. | Specified, pending. |
| `BinaryLogSink` | Append to the memory-mapped audit log. | Complete. |
| `KafkaSink` | Publish the protobuf envelope to the broker. | Specified, pending. |
| `NullSink` | Discard everything (`--dry-run`). | Complete. |
| `Pipeline` | The run loop. | Complete. |

The pending components are specified in
[`docs/architecture/overview.md`](../../docs/architecture/overview.md#milestones)
rather than stubbed out, so that the tree never contains code that lies
about what works.

## Invariants

* Quotes are written to the sink in the order the source produced them.
* A source failure is retried after the poll interval. It never terminates
  the process: process lifetime belongs to the supervisor.
* `SIGINT` and `SIGTERM` stop the loop gracefully. The current batch is
  drained, the audit log is flushed and synced, and the process exits 0.
* The upstream quota is respected: at most one request per second, and at
  most `IVOL_MAX_CONCURRENCY` requests in flight.

## Running

```bash
cmake --preset dev && cmake --build --preset dev

# offline replay
build/bin/volpulse-ingestion \
  --replay var/replay/aapl.ndjson \
  --binary-log var/binary-logs/options.vlog \
  --no-dry-run

# with the checked-in configuration
build/bin/volpulse-ingestion --config config/ingestion.conf
```

## Configuration

The service reads a flat `key = value` file, deliberately without a YAML
dependency: a long-running daemon whose configuration is mounted into a
container should not fail to start because of a parser.

```bash
build/bin/volpulse-ingestion --help
```

| Key | Meaning | Default |
| --- | --- | --- |
| `symbols` | Comma separated underlyings to poll. | empty |
| `binary_log` | Path of the audit log. | `var/binary-logs/options.vlog` |
| `replay` | Replay source; empty means live polling. | empty |
| `max_batch` | Quotes per poll. | 512 |
| `poll_interval` | Idle poll interval, in seconds. | 1.0 |
| `dry_run` | When true, nothing is written to the log. | true |

The canonical description of these values lives in
[`config/ingestion.yaml`](../../config/ingestion.yaml).

## Tests

```bash
ctest --preset dev --output-on-failure
```

The suite covers the configuration parser, the quote codec round trip, the
pipeline writing a log that can be read back, and the NDJSON reader.
