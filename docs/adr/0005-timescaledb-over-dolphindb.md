# ADR-0005: Use TimescaleDB rather than DolphinDB

* **Status:** Accepted
* **Date:** 2026-10-21
* **Deciders:** Platform owner

## Context

The brief offers a choice between **TimescaleDB** and **DolphinDB** for the
time-series store, noting that both have community tiers.

Both are serious systems:

* **TimescaleDB** is a PostgreSQL extension. It inherits PostgreSQL's
  transaction model, its SQL dialect, its ecosystem (psql, pg_dump, every
  ORM, every BI tool) and its operational familiarity.
* **DolphinDB** is a purpose-built columnar time-series database. It is
  substantially faster on analytical scans over wide, deeply partitioned
  data, and it has its own scripting language.

The pipeline's time-series workload is: append normalised quotes at market
rate, query them by underlying and time range, maintain fitted surfaces and
portfolio risk. The relational store is *also* required by the brief for
portfolio metadata and system state.

## Decision

Use **TimescaleDB** for time series and **PostgreSQL** for relational
state.

* TimescaleDB stores `option_quotes`, `volatility_surfaces` and
  `portfolio_risk` as hypertables, partitioned on the event time.
* A continuous aggregate (`option_quotes_daily`) keeps the dashboard queries
  cheap over long windows.
* PostgreSQL stores `positions`, `portfolios`, `ingestion_checkpoints` and
  `emitted_signals`.
* The two stores are separate databases, in separate containers, with
  separate credentials. The brief treats them as one "relational storage"
  layer, but mixing a hypertable workload and a transactional workload in
  one database couples their tuning and their failure modes.

The schema is applied twice, idempotently: by the container entrypoint on
first boot, and by the service at startup. Neither path is allowed to
depend on the other.

## Consequences

### What becomes easier

* One SQL dialect for everything. The analytics code, the migration
  scripts, the operational queries and the dashboards all speak the same
  language.
* The time-series store is not a new technology to operate: it is
  PostgreSQL, with backups, replication and monitoring that the team
  already understands.
* The surface and risk tables are ordinary relational tables for querying
  purposes — a "last surface for AAPL" is a plain `SELECT`, not a
  specialised query language.
* The C++ and Python sides need one PostgreSQL driver, not two.

### What becomes harder

* TimescaleDB is slower than a purpose-built columnar engine on very large
  analytical scans. If the dataset grows to the point where that matters,
  the continuous aggregates are the mitigation, and beyond that the
  analytics move to Parquet artefacts rather than to the database.
* The two-database split means two things to back up and two things to
  restore, and a restore has to be ordered correctly.

### What is now forbidden

* Writing hot-path tick data to PostgreSQL proper. Time series belongs in
  the hypertable; the relational store holds state that is updated.
* Storing Parquet artefacts in the database. Heavy artefacts live on disk
  under `var/artifacts/` and in object storage; the database holds the
  index and the queryable summary.

## Alternatives considered

### DolphinDB

Rejected. It is the faster engine for the analytical scan, and the brief's
"ultra-low-latency" framing favours it. Against it: it is a second
language for the data layer, its scripting language would be a new thing for
every operator to learn, and its ecosystem for the transactional state the
brief also requires does not exist. The performance advantage addresses a
scan pattern that this pipeline does not yet have, at the cost of a
second operational specialisation.

### One PostgreSQL for everything

Rejected. The hypertable workload and the transactional workload have
opposite tuning requirements: chunked, append-heavy, vacuum-hostile versus
small, row-locked, frequently updated. Coupling them means the tuning of
one is constrained by the other, and a checkpoint write can be delayed by a
bulk tick insert.

### Parquet on object storage as the system of record

Rejected for now, kept as the likely end state for the tick archive. The
brief requires queryable time series, and the Parquet artefacts already
exist — they are the intermediate artefact of the backfill. The database
remains the queryable surface; the artefacts remain the cheap archive.
