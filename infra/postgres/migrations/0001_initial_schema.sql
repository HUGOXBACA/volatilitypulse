-- ─────────────────────────────────────────────────────────────────────────────
-- VolPulse relational schema (PostgreSQL).
--
-- Holds the state that is updated rather than appended: open positions,
-- portfolio metadata, consumer checkpoints and the record of emitted signals.
-- Applied automatically by the container entrypoint on first boot, and
-- idempotently by the analytics engine at startup (see
-- volpulse_analytics.persistence.postgres.postgres_ddl).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id text PRIMARY KEY,
    description  text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS positions (
    contract_id      text        PRIMARY KEY,
    underlying_symbol text       NOT NULL,
    strike           double precision NOT NULL,
    right            text        NOT NULL,
    quantity         double precision NOT NULL,
    avg_entry_price  double precision NOT NULL,
    opened_at        timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS positions_underlying_idx ON positions (underlying_symbol);

CREATE TABLE IF NOT EXISTS ingestion_checkpoints (
    topic      text        NOT NULL,
    partition  integer     NOT NULL,
    offset     bigint      NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (topic, partition)
);

CREATE TABLE IF NOT EXISTS emitted_signals (
    signal_id         uuid        PRIMARY KEY,
    portfolio_id      text        NOT NULL,
    underlying_symbol text        NOT NULL,
    contract_id       text        NOT NULL,
    kind              text        NOT NULL,
    zscore            double precision NOT NULL,
    emitted_at        timestamptz NOT NULL DEFAULT now()
);

-- A signal is only actionable once: the lookup index makes the duplicate
-- check cheap enough to do inside the write transaction.
CREATE INDEX IF NOT EXISTS emitted_signals_lookup
    ON emitted_signals (contract_id, kind, emitted_at);
