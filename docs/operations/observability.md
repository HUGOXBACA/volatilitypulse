# Operations

## Observability model

VolPulse uses four tools, each with one job:

| Tool | Job | Configuration |
| --- | --- | --- |
| **Prometheus** | Time-series metrics, recording and alerting rules | `infra/prometheus/` |
| **Grafana** | Dashboards for humans | `infra/grafana/` |
| **InfluxDB** | Long-horizon metrics for trend analysis | `infra/influxdb/` |
| **Sensu** | Dispatching alerts to the on-call rotation | `infra/sensu/` |

The rule of thumb: **Prometheus answers "is it healthy right now", InfluxDB
answers "is it getting worse".** Anything that needs a long window or a
cross-service join belongs in InfluxDB.

## Metrics

All metrics are defined in one place — `volpulse_core.observability.metrics`
— so that the names cannot drift between the service and the dashboards.
The names are part of the operational contract: renaming one breaks the
dashboards and the rules.

### Consumer

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `volpulse_quotes_consumed_total` | counter | `underlying` | Quotes accepted. |
| `volpulse_quotes_dropped_total` | counter | `underlying`, `reason` | Quotes rejected. |
| `volpulse_end_to_end_latency_seconds` | histogram | `underlying` | Upstream event time to analytics output. |
| `volpulse_consumer_lag_seconds` | gauge | `topic`, `partition` | Age of the oldest queued record. |

### Surfaces and risk

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `volpulse_surface_fit_duration_seconds` | histogram | `underlying` | Time to fit a slice. |
| `volpulse_surface_fit_rms_error` | gauge | `underlying` | Quality of the latest fit. |
| `volpulse_surface_arbitrage_violations_total` | counter | `underlying`, `kind` | Static arbitrage detected. |
| `volpulse_greek_calculations_total` | counter | `underlying` | Greek evaluations. |

### Upstream and storage

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `volpulse_upstream_request_duration_seconds` | histogram | `endpoint` | Upstream call duration. |
| `volpulse_upstream_pacing_delay_seconds` | gauge | — | How hard the client is throttled. |
| `volpulse_persistence_write_duration_seconds` | histogram | `store` | Time spent writing. |

## Alerts

Rules live in `infra/prometheus/rules/pipeline.yml`. Every rule has:

* a `severity` label (`critical`, `warning`, `info`),
* a `runbook` annotation pointing at the file in `docs/runbooks/`,
* a `for` clause, so a momentary blip does not page anyone.

| Alert | Fires when | Severity |
| --- | --- | --- |
| `IngestionStalled` | No quotes consumed for 5 minutes | critical |
| `AnalyticsConsumerLag` | Lag above 30 s for 2 minutes | warning |
| `KafkaQueueDepthSpike` | Queue depth above 50 000 for 3 minutes | warning |
| `SurfaceFitDegraded` | Fit RMS error above 0.01 for 10 minutes | warning |
| `UpstreamPacingSaturated` | Pacing delay above 0.9 s for 10 minutes | info |
| `ArbitrageViolationsDetected` | Any new arbitrage violation | warning |

**Adding an alert means adding a runbook.** The `runbook` annotation is not
optional: a rule that fires without instructions is a page without a plan,
and it trains the rotation to ignore pages.

## Dashboards

`infra/grafana/dashboards/pipeline-overview.json` is provisioned
automatically. It shows the quote rate, consumer lag, end-to-end latency,
surface fit error, arbitrage violations, upstream pacing and write
durations.

When you add a panel, add the metric to `volpulse_core.observability.metrics`
first. A dashboard that queries a metric nobody exports is a broken
dashboard.

## Logging

Structured JSON, one object per line, fields documented in
`config/logging.yaml`. The redaction list in that file is binding: the
following are never logged, even inside an exception message:

`api_key`, `authorization`, `password`, `token`, `secret`.

Routine per-quote events are sampled at 1%; errors are never sampled.

## SLOs

| Objective | Target | Measured by |
| --- | --- | --- |
| Pipeline availability | 99.5% of the trading day | `volpulse_quotes_consumed_total` > 0 |
| End-to-end latency | p95 below 1 s | `volpulse_end_to_end_latency_seconds` |
| Consumer lag | below 5 s at p95 | `volpulse_consumer_lag_seconds` |
| Surface fit error | below 0.005 at p95 | `volpulse_surface_fit_rms_error` |
| Data loss | zero records dropped that were not rejected by the schema | `volpulse_quotes_dropped_total` |

## Runbook index

See [`docs/runbooks/README.md`](../runbooks/README.md).
