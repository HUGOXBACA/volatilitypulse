# ADR-0003: Standardise on Kafka rather than BlazingMQ

* **Status:** Accepted
* **Date:** 2026-10-21
* **Deciders:** Platform owner

## Context

The brief offers a choice between **BlazingMQ** and **Kafka** for the
messaging layer, and describes BlazingMQ as a way to "highlight cutting-edge
tech".

BlazingMQ is a genuinely capable broker with a lower latency profile than
Kafka, and it is used in production at several tier-one firms. Kafka is the
dominant broker in market data infrastructure generally, and it is the one
that a reader of this repository is most likely to already be able to run.

Both were on the table, and the choice was not made on latency: the pipeline
described in the brief already has a Python consumer, a C++ producer, a
time-series store and a monitoring stack. Latency at the broker is not the
binding constraint — the upstream API is metered at roughly one request per
second, which is four orders of magnitude slower than either broker.

## Decision

Standardise on **Kafka**, and run it in KRaft mode (no ZooKeeper).

* The Python client is `confluent-kafka`; the C++ client is `librdkafka`.
* Topics are partitioned by underlying symbol so that per-symbol ordering
  is guaranteed.
* Retention is explicit per topic and recorded in `infra/kafka/topics.sh`:
  seven days for the streaming topic, one day for the realtime topic, thirty
  days for the dead-letter topic.
* Consumer offsets are committed **manually, after the analytics result is
  durable**. The broker retains the backlog, so a crash costs time rather
  than data.

The abstract `QuoteSource` / `QuoteSink` interfaces in the ingestion engine
mean that the broker is not visible to the ingestion logic. The audit log
already holds what was produced, so the transport is replaceable.

## Consequences

### What becomes easier

* The local infrastructure is one `docker compose` service with a
  well-trodden image, and the topic creation is a checked-in script rather
  than bespoke configuration.
* The ecosystem is large: the Python and C++ clients are the best-supported
  in their respective languages, and the operational tooling (schema
  registry, lag dashboards, replay tooling) already exists.
* Kafka's retention gives a natural replay window, which complements the
  binary audit log rather than duplicating it.
* Nobody has to learn a broker that is used by a handful of firms.

### What becomes harder

* Kafka's latency floor is higher than BlazingMQ's. This is currently
  irrelevant — the upstream quota dominates by four orders of magnitude —
  but it becomes relevant if the upstream is ever replaced with a feed that
  is not metered.
* Partition count, replication factor and retention have to be managed.
  Under-provisioning a partition count is the classic Kafka scaling mistake,
  and it cannot be changed in place for an existing topic.
* Running Kafka locally costs more memory than a lighter broker would.

### What is now forbidden

* Auto-creating topics in the broker (`auto.create.topics.enable=false`).
  Topics are created by `make topics`, with an explicit retention policy.
* Auto-committing consumer offsets. The commit happens after the write is
  durable.
* Publishing to the streaming topic with a key that is not the underlying
  symbol: the partitioning guarantee is what makes the surfaces well
  defined.

## Alternatives considered

### BlazingMQ

Rejected for now, kept as a live option. It is the right answer if the
upstream ever becomes unthrottled and the latency budget becomes
sub-millisecond end to end. The `QuoteSink` interface is the seam where it
would be swapped in, and the audit log means the swap does not put the data
at risk. Revisit if the end-to-end latency target changes.

### Redis Streams

Rejected. Simpler, but the consumer-group and retention semantics are
weaker, the operational tooling is thinner, and the broker would become the
single point of failure with no replication story that we would want to
operate.

### A managed cloud broker

Rejected for the local and self-hosted deployment this repository targets.
The compose stack keeps the whole pipeline reproducible on a laptop, which
is what makes the rest of the system testable at all.
