# Runbook: the fitted surfaces have degraded

**Alert:** `SurfaceFitDegraded` — the RMS error of the surface fit is above
0.01 for ten minutes.
**Severity:** warning
**Service:** `volpulse-analytics`

## Symptom

`volpulse_surface_fit_rms_error` is above 0.01. The fitted implied
volatility surfaces no longer describe the market well.

The threshold is a total variance error of 0.01, which is roughly a
volatility error of one volatility point at a 20% level. A surface that is
wrong by that much will produce mispricing signals that are noise.

**This alert does not mean the pipeline is broken.** The pipeline may be
perfectly healthy and the market may simply have moved.

## Assess

```bash
curl -s http://localhost:9100/metrics | grep -E 'surface_fit|arbitrage'
```

| Metric | Reading |
| --- | --- |
| `volpulse_surface_fit_rms_error` high, fit duration normal | The data or the model does not fit. |
| `volpulse_surface_fit_duration_seconds` also high | The optimiser is struggling, which usually means the data is noisy or the slice is ill-conditioned. |
| `volpulse_surface_fit_rms_error` high for one underlying only | An event in that market, not a system problem. |
| High for every underlying | A data problem, or a model problem. |

## One underlying only

A single underlying with a bad fit is almost always the market, not the
system: a large move, an earnings event, an expiry roll, or a strike ladder
that is temporarily lopsided.

**Safe:** do nothing. The fit recovers when the market settles. Do not
re-fit with different parameters to make the error go away — that hides the
signal instead of explaining it.

## Every underlying

### Is the data clean?

```bash
curl -s http://localhost:9100/metrics | grep volpulse_quotes_dropped
```

A jump in dropped quotes means the upstream is returning something the
schema rejects, and the surface is being fitted on partial data.

```bash
docker compose logs --tail=200 analytics | grep -i 'schema\|dropped\|invalid'
```

### Is the slice well conditioned?

The SVI fitter needs at least `analytics.minimum_points_per_slice` usable
points per slice (4 by default). If the chain is thin — few strikes, or
many quotes with no implied volatility — the fit is under-determined.

```sql
-- in TimescaleDB
SELECT underlying_symbol, expiry_epoch_day, count(*)
FROM option_quotes
WHERE event_time > now() - INTERVAL '1 hour'
GROUP BY 1, 2
ORDER BY 3 ASC
LIMIT 20;
```

Slices with very few points produce large errors legitimately.

### Is the model appropriate?

Raw SVI is linear in the wings, which is a good default but not
universal. A market with a sharp kink (a known event) may genuinely not be
a smooth slice. This is a modelling decision, not an incident response:
raise it with the platform owner rather than changing the model during an
alert.

### The forward is wrong

The fit uses the forward price of the underlying to compute log-moneyness.
A wrong forward shifts every point of the slice and inflates the residual.

```bash
grep -i 'spot_provider\|forward' docker compose logs --tail=100 analytics
```

## Arbitrage violations

`volpulse_surface_arbitrage_violations_total` increments when a fitted
surface implies a negative density — a butterfly arbitrage.

**This is information, not a defect.** The check exists so that an
arbitrageable surface is published with `arbitrage_free = false` and is
never traded on.

| Situation | Action |
| --- | --- |
| A few violations in a volatile market | Expected. The market itself is occasionally arbitrageable. |
| Violations on every fit for one underlying | The quotes may contain crossed or stale prices, which distort the slice. Check `volpulse_quotes_dropped_total`. |
| Violations on every fit for every underlying | Something is wrong with the data path. Escalate. |

**Never** widen the arbitrage check to make the alert stop. The check is
the safety property; the alert is the notification.

## Escalation

Escalate to the platform owner if:

* every underlying is affected for more than an hour, or
* violations are being emitted continuously for every underlying, or
* the fit duration has also degraded (the optimiser is not converging).

Include the metrics dump, the slice-count query above, and a sample of the
rejected quotes.
