# Runbook: the broker queue depth has spiked

**Alert:** `KafkaQueueDepthSpike` — more than 50 000 records queued.
**Severity:** warning
**Service:** `volpulse-ingestion`

## Symptom

`volpulse_broker_queue_depth` is above 50 000 on one or more partitions.
The producer is filling the broker faster than the consumer is emptying it.

This is a **backpressure** signal, not a failure: the broker is doing its
job. It matters because the backlog can eventually exceed the retention
window, and because a deep backlog means the analytics engine is working on
stale quotes.

## Assess

```bash
docker compose exec kafka kafka-consumer-groups.sh \
  --bootstrap-server kafka:9092 \
  --describe --group volpulse-analytics
```

| Finding | Diagnosis |
| --- | --- |
| Lag is growing on every partition | The consumer is slower than the producer. |
| Lag is growing on one partition only | A hot symbol, or a stuck consumer. |
| Lag is flat and high | A burst that is being worked through. |

```bash
curl -s http://localhost:9100/metrics | grep -E 'consumer_lag|quotes_consumed'
```

## It is a burst

A large upstream backfill, or a restart of the ingestion engine that
re-published a window, produces a spike that drains on its own.

**Safe:** wait. Watch the lag fall:

```bash
watch -n 10 'docker compose exec kafka kafka-consumer-groups.sh \
  --bootstrap-server kafka:9092 --describe --group volpulse-analytics'
```

Do **not** restart the consumer to "clear" the queue: it will resume from
the committed offset and re-read the backlog, making the queue deeper.

## One partition is hot

A single partition holding the whole backlog usually means the producer is
not keying by symbol, so all records land on one partition.

```bash
docker compose logs --tail=200 ingestion | grep -i 'partition'
```

**Safe:** fixing the keying only affects new records. Existing records stay
in the partition they were written to.

## The consumer is slower than the producer

Work through [consumer-lag.md](consumer-lag.md). The causes are the same:
a slow database write, an expensive surface fit, or a starved consumer.

## When the backlog is genuinely dangerous

The retention window on `options.chain.streaming` is seven days
(`infra/kafka/topics.sh`). If the backlog is growing faster than the
consumer can drain it, the oldest records will be dropped when they age
out.

Two options, in order of preference:

1. **Reduce the production rate.** Lower the number of symbols polled, or
   lower the refresh frequency. This stops the backlog growing. Quotes stop
   being refreshed, but nothing is lost that has not already been consumed.

2. **Scale the consumer.** Start a second instance of the analytics engine
   in the same consumer group:

   ```bash
   docker compose up -d --scale analytics=2
   ```

   **Safe:** the consumer group guarantees that each partition is owned by
   exactly one member, so a second instance takes over partitions rather than
   double-processing them.

   Scale back in with `docker compose up -d --scale analytics=1`.

## Escalation

Escalate if the backlog is still growing after an hour of the steps above.
Include the consumer group description, the metrics dump and the ingestion
rate. The question for the platform owner is whether to throttle the
producer or scale the consumer.
