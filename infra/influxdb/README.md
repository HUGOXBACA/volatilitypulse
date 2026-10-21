# InfluxDB

**Status:** configured, not yet a primary sink.

## Role

Prometheus answers "is it healthy right now". InfluxDB answers "is it
getting worse" — it keeps the long-horizon metrics that the Prometheus
retention window (15 days) is too short for.

| What | Where it goes |
| --- | --- |
| Live metrics, alerting | Prometheus |
| End-to-end latency trends over weeks | InfluxDB |
| Consumer lag history per partition | InfluxDB |
| Upstream quota consumption over time | InfluxDB |

The rule of thumb: a metric that needs a window longer than a fortnight
belongs in InfluxDB, and a metric that someone might page on belongs in
Prometheus.

## Configuration

| Setting | Value |
| --- | --- |
| URL | `http://localhost:8086` |
| Organisation | `volpulse` |
| Bucket | `metrics` |
| Token | `INFLUXDB_TOKEN` (default `volpulse-dev-token`) |

The bucket is created by the container entrypoint on first boot, with the
retention policy below.

## Retention

| Measurement | Retention |
| --- | --- |
| `pipeline_latency` | 90 days |
| `consumer_lag` | 30 days |
| `upstream_quota` | 30 days |
| `surface_quality` | 365 days |

Surface quality is kept for a year because it is the metric that shows
whether a modelling change improved anything, and that comparison needs a
long baseline.

## Writing

The services push to InfluxDB through a write endpoint, batched every ten
seconds. The write is best-effort: a failure to write to InfluxDB must
never stall the pipeline, so errors are counted and dropped, not retried
indefinitely.
