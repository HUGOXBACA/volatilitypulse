# Architectural decision records

An ADR records a decision that has consequences beyond the sprint that made
it. Once a decision is accepted, it is not edited: a change of mind is a
**new** ADR that supersedes the old one, so the history stays readable.

## Format

Each record lives in `NNNN-title.md` and has the sections below. Keep it to
one page: an ADR that needs ten pages is a design document, and design
documents belong in `docs/architecture/`.

| Section | What goes in it |
| --- | --- |
| **Status** | Proposed, Accepted, Superseded by ADR-NNNN, Deprecated. |
| **Context** | The forces at play. Not a history of the project. |
| **Decision** | What was decided, in the active voice. |
| **Consequences** | What becomes easier, what becomes harder, what is now forbidden. |
| **Alternatives considered** | What else was on the table and why it lost. |

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-polyglot-monorepo-layout.md) | Organise the repository as a polyglot monorepo | Accepted |
| [0002](0002-binary-audit-log-before-transport.md) | Build the binary audit log before the transport layer | Accepted |
| [0003](0003-kafka-over-blazingmq.md) | Standardise on Kafka rather than BlazingMQ | Accepted |
| [0004](0004-accelerator-deferral.md) | Defer CUDA and FPGA acceleration | Accepted |
| [0005](0005-timescaledb-over-dolphindb.md) | Use TimescaleDB rather than DolphinDB | Accepted |

## Process

1. Open a PR containing a new ADR with the status `Proposed`.
2. Discuss it in the PR. The decision is made by the person who owns the
   system, not by consensus.
3. Merge with the status `Accepted` and update the index above.
4. If the decision is later reversed, write a new ADR and mark the old one
   `Superseded by ADR-NNNN`.
