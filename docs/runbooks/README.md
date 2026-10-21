# Runbooks

A runbook answers the question you have at 03:00: **what do I do about
this?** Every alerting rule in `infra/prometheus/rules/pipeline.yml` has a
runbook here, and the mapping is written into the rule itself.

## Index

| Alert | Severity | Runbook |
| --- | --- | --- |
| `IngestionStalled` | critical | [ingestion-stalled.md](ingestion-stalled.md) |
| `AnalyticsConsumerLag` | warning | [consumer-lag.md](consumer-lag.md) |
| `KafkaQueueDepthSpike` | warning | [queue-depth-spike.md](queue-depth-spike.md) |
| `SurfaceFitDegraded` | warning | [surface-degraded.md](surface-degraded.md) |
| `UpstreamPacingSaturated` | info | [ingestion-stalled.md#the-upstream-is-permanently-throttled) |
| `ArbitrageViolationsDetected` | warning | [surface-degraded.md#arbitrage-violations) |

## Rules for writing a runbook

1. **Start with the symptom, not the theory.** The reader is paged; they
   need to know what they are looking at.
2. **Every command must be copy-pasteable** and must work in the environment
   the alert fires in.
3. **Say what is safe to do.** Half the value of a runbook is knowing which
   action is harmless.
4. **End with the escalation.** Who to wake, and when.
5. **No theory longer than two paragraphs.** Depth belongs in
   `docs/architecture/`.

## Before you start

```bash
cd /path/to/volatilitypulse
source .env                      # or: set -a; source .env; set +a
make infra-logs                  # tail the whole stack
docker compose ps                # what is running, and is it healthy
```

`docker compose ps` is the first command in every runbook: a service that
is not running produces every symptom in this document.
