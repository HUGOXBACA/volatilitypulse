-- ─────────────────────────────────────────────────────────────────────────────
-- VolPulse time-series schema (TimescaleDB).
--
-- Applied automatically by the container entrypoint on first boot, and
-- idempotently by the analytics engine at startup (see
-- volpulse_analytics.persistence.timescale.timescale_ddl).
--
-- Everything here is append-only and queried by time range: that is what the
-- hypertable layout is for.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS option_quotes (
    contract_id         text        NOT NULL,
    underlying_symbol   text        NOT NULL,
    expiry_epoch_day    integer     NOT NULL,
    strike              double precision NOT NULL,
    right               text        NOT NULL,
    bid                 double precision NOT NULL,
    ask                 double precision NOT NULL,
    last                double precision NOT NULL,
    close               double precision NOT NULL,
    implied_volatility  double precision,
    event_time          timestamptz NOT NULL,
    ingest_time         timestamptz NOT NULL,
    sequence            bigint      NOT NULL,
    source              text        NOT NULL,
    PRIMARY KEY (contract_id, event_time)
);

SELECT create_hypertable('option_quotes', 'event_time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS option_quotes_underlying_time_idx
    ON option_quotes (underlying_symbol, event_time DESC);

CREATE TABLE IF NOT EXISTS volatility_surfaces (
    underlying_symbol  text        NOT NULL,
    as_of              timestamptz NOT NULL,
    expiry_epoch_day   integer     NOT NULL,
    strike             double precision NOT NULL,
    implied_volatility double precision NOT NULL,
    fit_method         text        NOT NULL,
    rms_error          double precision NOT NULL,
    arbitrage_free     boolean     NOT NULL,
    PRIMARY KEY (underlying_symbol, as_of, expiry_epoch_day, strike)
);

SELECT create_hypertable('volatility_surfaces', 'as_of', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS portfolio_risk (
    portfolio_id   text        NOT NULL,
    as_of          timestamptz NOT NULL,
    delta          double precision NOT NULL,
    gamma          double precision NOT NULL,
    vega           double precision NOT NULL,
    theta          double precision NOT NULL,
    rho            double precision NOT NULL,
    gross_notional double precision NOT NULL,
    net_notional   double precision NOT NULL,
    PRIMARY KEY (portfolio_id, as_of)
);

SELECT create_hypertable('portfolio_risk', 'as_of', if_not_exists => TRUE);

-- Continuous aggregates keep the dashboards cheap on large windows.
CREATE MATERIALIZED VIEW IF NOT EXISTS option_quotes_daily
WITH (timescaledb.continuous) AS
SELECT
    underlying_symbol,
    time_bucket('1 day', event_time) AS day,
    expiry_epoch_day,
    avg(implied_volatility) AS avg_implied_volatility,
    max(implied_volatility) AS max_implied_volatility,
    min(implied_volatility) AS min_implied_volatility,
    count(*)                      AS quote_count
FROM option_quotes
WHERE implied_volatility IS NOT NULL
GROUP BY underlying_symbol, day, expiry_epoch_day
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'option_quotes_daily',
    start_offset => INTERVAL '3 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes'
);
