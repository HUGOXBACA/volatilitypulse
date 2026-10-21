# Glossary

The vocabulary of the desk and of the codebase.

## Market

**Option** — a derivative that gives the holder the right, but not the
obligation, to buy (call) or sell (put) an underlying at a fixed strike on
or before an expiry.

**Underlying** — the asset an option is written on. In VolPulse it is
identified by its symbol, e.g. `AAPL`.

**Strike** — the price at which the underlying may be bought or sold.

**Expiry** — the date on which the option lapses. VolPulse stores expiries
as an **epoch day count** (days since 1970-01-01, UTC), because an expiry is
a date and not an instant.

**Chain** — every option contract on one underlying at one point in time.

**Quote** — the prices of a single contract: bid, ask, last, close.

**Mid** — the midpoint of the best bid and ask. Falls back to the last
traded price when the book is empty.

**Spread** — the difference between the best ask and the best bid.

**Forward** — the price at which the underlying is contracted to trade at
expiry. `F = S · e^{(r−q)T}`.

**Log-moneyness** — `k = log(K / F)`. The horizontal axis of a volatility
surface.

## Volatility

**Implied volatility (IV)** — the volatility that, substituted into a pricing
model, reproduces the observed option price. A decimal: `0.25` is 25%.

**Total variance** — `w = σ²T`. The quantity a surface is actually fitted
to, because it is additive across time. This is what the SVI model fits.

**Surface** — implied volatility as a function of strike and expiry. In
VolPulse it is fitted one expiry slice at a time.

**SVI** — the *Stochastic Volatility Inspired* parametrisation of a
volatility slice (Gatheral). Raw SVI:

```
w(k) = a + b · (ρ(k − m) + √((k − m)² + σ²))
```

where `a` is the overall level, `b` the slope, `ρ` the skew, `m` the
horizontal shift and `σ` the curvature of the wings.

**Butterfly arbitrage** — the possibility of a riskless profit from a
combination of three contracts with the same expiry. It corresponds to a
negative risk-neutral density, and Lee's moment formula detects it: the
density implied by the slice must not go negative.

**Calendar arbitrage** — a riskless profit from a longer-dated and a
shorter-dated contract at the same strike. It corresponds to total variance
decreasing with time, which must not happen.

**Skew** — the dependence of implied volatility on strike. Negative skew
means puts are bid.

**Surface arbitrage** — a fitted surface that permits a butterfly or
calendar arbitrage. VolPulse publishes such a surface with
`arbitrage_free = false` and never trades it.

## Risk

**Delta** — the sensitivity of the option price to the underlying. Also the
probability of finishing in the money under the risk-neutral measure.

**Gamma** — the sensitivity of delta to the underlying. Largest at the
forward strike, zero at expiry.

**Vega** — the sensitivity of the option price to volatility.

**Theta** — the sensitivity of the option price to time. VolPulse quotes it
per calendar day.

**Rho** — the sensitivity of the option price to the interest rate.

**Aggregate risk** — the portfolio-level sum of the position-level Greeks,
weighted by signed quantity and contract multiplier.

## Pipeline

**Normalisation** — converting a provider payload into the canonical
`OptionQuote` message. VolPulse normalises at the edge, so that everything
downstream sees exactly one representation.

**Binary audit log** — the append-only, memory-mapped, CRC-checked file of
everything the ingestion engine produced. It is what makes the pipeline
replayable.

**Torn tail** — a partially written record at the end of the log, left by a
crash. The writer detects it on the next open and truncates it.

**Sequence number** — the monotonic identifier of a record within a log
file. Gap-free within one file.

**Checkpoint** — the durable record of how far the pipeline has progressed:
the last broker offset published, or the last upstream page fetched.

**Replay** — re-running the pipeline over recorded input, from the audit
log rather than from the upstream.

**Backfill** — a historical data pull, fetched asynchronously: the provider
returns a job, the engine polls it until the download is published, then
walks the result page by page.

**Consumer group** — the set of analytics instances that share the work of
reading the broker. Each partition is owned by exactly one member.

**Consumer lag** — the age of the oldest record still queued in a partition.

## Operations

**SLO** — a service level objective: the target a measurable quantity is
held to.

**Runbook** — the document that says what to do when an alert fires.

**ADR** — an architectural decision record: a written decision with its
context, its consequences and the alternatives that were rejected.

**Pacing** — the deliberate rate limiting of upstream calls. The upstream
subscription allows roughly one request per second, and VolPulse owns that
limit in one place so that no component can burst past it.
