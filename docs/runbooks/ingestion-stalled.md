# Runbook: the ingestion pipeline has stalled

**Alert:** `IngestionStalled` — no quotes consumed for five minutes.
**Severity:** critical
**Service:** `volpulse-analytics` (the symptom appears downstream)

## Symptom

`volpulse_quotes_consumed_total` has a zero rate for five minutes, and the
dashboard shows the quote rate flat at zero. The analytics engine is
running — it is not crashing — but nothing is arriving.

## First: is anything running?

```bash
docker compose ps
```

| What you see | Go to |
| --- | --- |
| The ingestion engine is not running | [The ingestion engine is down](#the-ingestion-engine-is-down) |
| The ingestion engine is running but the consumer is not | [The consumer is down](#the-consumer-is-down) |
| Everything is running | [The upstream is not delivering](#the-upstream-is-not-delivering) |

## The ingestion engine is down

```bash
docker compose logs --tail=200 ingestion
```

| Last log line | Meaning | Action |
| --- | --- | --- |
| `fatal: ...` | A configuration or startup error. | Fix the configuration and restart. |
| `checkpoint file ... corrupted` | The broker's metadata is damaged. | See [The broker metadata is damaged](#the-broker-metadata-is-damaged). |
| Nothing — the container is restarting | Crash loop. | `docker compose logs --tail=200 ingestion` and read the last stack trace. |

Restart:

```bash
docker compose restart ingestion
docker compose logs -f ingestion
```

**Safe:** the engine replays from its last checkpoint. Restarting does not
duplicate quotes that were already published, and it does not lose quotes
that were not.

## The consumer is down

```bash
docker compose logs --tail=200 analytics
docker compose ps analytics
```

A consumer that exits on a database error will not come back on its own if
the orchestrator is not restarting it. Check the error, fix the cause, and
restart:

```bash
docker compose restart analytics
```

The consumer resumes from the last committed offset. Because offsets are
committed *after* the write is durable, a crash re-processes at most one
batch — the results are idempotent, so this is safe.

## The upstream is not delivering

```bash
curl -s "https://api.ivolatility.com/v1/option/chains?symbol=AAPL" \
  -H "x-api-key: ${IVOL_API_KEY}" | head -c 500
```

| Response | Meaning | Action |
| --- | --- | --- |
| `401` / `403` | The API key is wrong, expired or over quota. | Check `IVOL_API_KEY` in `.env`. Check the subscription status with the provider. |
| `429` | Rate limited beyond the configured pacing. | See [The upstream is permanently throttled](#the-upstream-is-permanently-throttled). |
| `5xx` | The provider is down. | Wait. The engine retries on its own. Check the provider's status page. |
| A valid payload | The upstream is fine. | The engine is not polling the symbols it should — check `symbols` in `config/ingestion.conf`. |

### Check what the engine is actually doing

```bash
curl -s http://localhost:9101/metrics | grep -E 'volpulse_(upstream|quotes|ingest)'
```

| Metric | Reading |
| --- | --- |
| `volpulse_upstream_pacing_delay_seconds` near zero | The client is not being throttled — it is not making calls. |
| `volpulse_upstream_request_duration_seconds_count` flat | No requests are being made at all. |
| `volpulse_upstream_request_duration_seconds_count` climbing | Requests are being made and failing. Look at the error rate. |

## The upstream is permanently throttled

`volpulse_upstream_pacing_delay_seconds` is close to 1.0 for a sustained
period: the client is holding back the maximum it can.

1. Confirm the quota: the subscription allows roughly one request per
   second. If `IVOL_RATE_LIMIT_RPS` is above `1.0`, lower it to `1.0`.
2. Check how many symbols are configured. The engine cycles through them and
   each symbol costs one request per cycle. Four symbols at one request per
   second means one full refresh of every symbol every four seconds.
3. Check whether a backfill is running. A historical backfill competes with
   the live feed for the same quota — `volpulse_upstream_request_duration_seconds_count`
   will be climbing while live quotes stall. Let the backfill finish, or
   reduce its scope.

**Safe:** reducing the rate never loses data; it only slows the feed.

## The broker metadata is damaged

Symptom: the consumer logs `checkpoint file ... corrupted`, or the broker
refuses to start with a metadata error.

```bash
docker compose logs --tail=100 kafka
```

The broker's metadata lives in the `kafka-data` volume. If it is damaged
and the offsets in it are not needed (the audit log holds the data), the
volume can be rebuilt:

```bash
docker compose down kafka
docker volume rm volpulse_kafka-data
docker compose up -d kafka
make topics
```

**Destructive:** this deletes the broker's topics and their contents. The
binary audit log under `var/binary-logs/` is unaffected and can be replayed
into fresh topics. Never do this while a backfill is in progress.

## Escalation

If none of the above resolves it within 30 minutes, and the provider
status page shows an outage, escalate to the platform owner. Include:

* the output of `docker compose ps`,
* the last 200 lines of both service logs,
* the metrics dump from `curl -s http://localhost:9101/metrics`,
* the output of `make tree` so the reviewer knows the code version.
