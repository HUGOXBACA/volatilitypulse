# Runbook: the analytics consumer is behind

**Alert:** `AnalyticsConsumerLag` — more than 30 seconds behind.
**Severity:** warning
**Service:** `volpulse-analytics`

## Symptom

`volpulse_consumer_lag_seconds` is above 30. The dashboard shows the
consumer's position in the topic trailing the producer's position. Quotes
are still arriving, just later than they should.

Lag above a few seconds is normal during a burst. Lag that grows
monotonically is not: it means the consumer cannot keep up with the rate at
which quotes are produced, and it will eventually exhaust the retention
window and lose data.

## Assess: is it catching up or falling behind?

```bash
curl -s http://localhost:9100/metrics | grep volpulse_consumer_lag
```

Watch it for two minutes.

| Pattern | Diagnosis | Go to |
| --- | --- | --- |
| Falling steadily to zero | The consumer is catching up. | [It is catching up](#it-is-catching-up) |
| Flat at a high value | The consumer is at its limit. | [It is at its limit](#it-is-at-its-limit) |
| Rising steadily | The producer is faster than the consumer, or one partition is stuck. | [It is falling behind](#it-is-falling-behind) |

## It is catching up

Nothing to do. A backlog after a restart, a redeploy or a pause in the
ingestion engine is normal and drains on its own.

Watch it drain:

```bash
watch -n 5 'curl -s http://localhost:9100/metrics | grep volpulse_consumer_lag'
```

**Safe:** do nothing. Restarting the consumer resets its position to the
committed offset and re-processes the backlog, which makes the lag worse,
not better.

## It is at its limit

The consumer is keeping up with the current rate but cannot go faster.
The usual cause is a slow downstream write.

```bash
curl -s http://localhost:9100/metrics | grep -E 'persistence_write_duration|surface_fit_duration'
```

| Metric | Reading | Action |
| --- | --- | --- |
| `volpulse_persistence_write_duration_seconds` p95 is high | The database is the bottleneck. | Go to [The database is the bottleneck](#the-database-is-the-bottleneck). |
| `volpulse_surface_fit_duration_seconds` p95 is high | The surface fit is the bottleneck. | Go to [The surface fit is the bottleneck](#the-surface-fit-is-the-bottleneck). |
| Both are low | The consumer is idle-waiting. | Check the broker: the consumer may be starved of partitions. |

### The database is the bottleneck

```bash
docker compose exec timescaledb psql -U volpulse -d volpulse -c \
  "SELECT pg_stat_activity.query, pg_stat_activity.state, now() - pg_stat_activity.query_start AS duration
   FROM pg_stat_activity WHERE datname = 'volpulse' ORDER BY duration DESC LIMIT 5;"
```

| Finding | Action |
| --- | --- |
| A long-running `COPY` | Expected during a burst. Wait. |
| `pg_stat_activity` shows waits on a lock | Another writer is holding a lock. Check for a stuck transaction. |
| The database is saturated on I/O | The volume is on the slow disk. Move `timescale-data` to faster storage, or reduce the write rate. |

**Safe:** the consumer will catch up once the database recovers. Restarting
it does not help and loses the work it has already done in memory.

### The surface fit is the bottleneck

A fit is attempted per underlying per expiry on every snapshot. If the
snapshot rate is high relative to the fitting cost, the lag grows.

1. Check how many expiries are being fitted:
   `volpulse_surface_fit_duration_seconds_count` divided by the number of
   snapshots per minute.
2. Raise `analytics.minimum_points_per_slice` in `config/analytics.yaml` if
   the slices are thin — a fit on four points is not worth its cost.
3. If the fit itself is slow, note it as a performance issue rather than
   changing behaviour during an incident. The `numba`/`JAX` path described
   in [ADR 0004](../adr/0004-accelerator-deferral.md) is the fix.

**Safe:** raising the minimum points per slice means fewer surfaces are
published. That is a behaviour change — do it during working hours, not
during an incident, unless the lag is actively losing data.

## It is falling behind

The producer is faster than the consumer, or a partition is stuck.

### Check the partition distribution

```bash
docker compose exec kafka kafka-consumer-groups.sh \
  --bootstrap-server kafka:9092 \
  --describe --group volpulse-analytics
```

| Finding | Meaning |
| --- | --- |
| One partition has a large lag and the rest are empty | The producer is not keying by symbol, or the consumer is not reading all partitions. |
| Lag is spread evenly | The consumer is simply slower than the producer. |

If the lag is spread evenly, the fix is throughput, not distribution: see
[It is at its limit](#it-is-at-its-limit).

### Check the producer

```bash
docker compose logs --tail=100 ingestion | grep -c 'published'
```

**Safe:** the ingestion engine publishes on its own schedule and is not
affected by the consumer's lag — the broker absorbs the difference. The
danger is only that the backlog eventually exceeds the retention window
(seven days), at which point the oldest records are dropped.

## Escalation

If lag exceeds the retention window — that is, if it persists for more than
a few hours — the oldest quotes are being discarded and a gap will appear in
the time series. Escalate to the platform owner with:

* the consumer group description above,
* the metrics dump,
* the ingestion rate (`volpulse_quotes_consumed_total` derivative).
