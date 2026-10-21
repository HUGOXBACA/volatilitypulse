# Broker transport

**Status:** specified, not implemented.

The publisher side of the messaging layer, and the consumer side in Python.

## Responsibility

* Publish the `ChainRecord` envelope to the broker, keyed by underlying
  symbol so that per-symbol ordering is guaranteed.
* Carry the byte offset of the source record in the audit log, so any
  consumed record can be replayed from disk without touching the broker.
* Commit the offset only after the downstream result is durable.

## Why the broker is not visible to the pipeline

The ingestion pipeline writes to a `QuoteSink`. The Kafka implementation is
one sink among several — the binary log is another, the null sink is
another. The transport is therefore replaceable without touching the
ingestion logic, and the audit log already holds what was produced.

That property is what makes [ADR 0003](../../../docs/adr/0003-kafka-over-blazingmq.md)
reversible: swapping the broker is a change to one class.

## Topic and keying

| Topic | Key | Retention |
| --- | --- | --- |
| `options.chain.streaming` | `underlying_symbol` | 7 days |
| `options.quotes.realtime` | `contract_id` | 1 day |
| `options.surfaces.recomputed` | `underlying_symbol` | 30 days |
| `options.chain.deadletter` | `underlying_symbol` | 30 days |

The key is the partitioning guarantee. A record whose key is not the
underlying symbol breaks the ordering that makes a snapshot well defined,
and the surfaces computed from it become meaningless.

## Delivery semantics

The producer uses the idempotent producer (a producer identity and epoch are
carried in the envelope), and the consumer commits manually. The combination
gives effectively-once processing: a crash re-processes at most one batch,
and the results are idempotent, so re-processing is harmless.
