# ADR-0001: Organise the repository as a polyglot monorepo

* **Status:** Accepted
* **Date:** 2026-10-21
* **Deciders:** Platform owner

## Context

VolPulse is polyglot by necessity. The ingestion path is latency sensitive
and belongs in C++; the analytics path is numerical and belongs in Python;
the contracts between them are protobuf. The repository already contained
both languages, in a layout that reflected neither:

* `src/c++` and `src/python` split the tree by *language*, which forced a
  feature that spans both sides to live in two unrelated places;
* `setup/setup.py` sat next to a Poetry-managed `pyproject.toml`, so there
  were two packaging systems and one of them was empty;
* `data/db`, `data/kafka` and `logs/` were committed directories for
  runtime state;
* the C++ and Python halves had no shared vocabulary, so the fields of a
  quote were defined twice — once in each language — and nothing kept them
  in agreement.

The question is how to organise a repository that contains two languages, one
broker, two databases and a monitoring stack, such that a reader can answer
"where does this live?" in under a minute, and such that a change to a
contract cannot silently diverge between the two sides.

## Decision

Organise the repository as a **polyglot monorepo with four top-level
concerns**:

1. **`contracts/`** — every message that crosses a service boundary is a
   protobuf file, and nothing else may define such a message. Field numbers
   are frozen. Both languages generate their stubs from the same source.
2. **`services/`** — deployable units, one directory per process. A service
   may depend on contracts and on `libs/`.
3. **`libs/`** — reusable code that is not a process. It may depend on
   contracts and on the standard library, never on a service.
4. **`infra/`** — the infrastructure the services run against. It never
   imports application code.

Supporting directories: `config/` (non-secret runtime configuration),
`docs/` (architecture, ADRs, runbooks, operations), `tools/` (bootstrap,
code generation, seeding), `tests/` (cross-service integration and
end-to-end), `var/` (runtime state, gitignored).

Language is expressed *within* a concern, not as the top-level axis. A
service is `ingestion-cpp` or `analytics-py`; the suffix removes ambiguity
without making the tree unreadable.

Dependencies point downwards only: `services` → `libs` → standard library.
The one exception is configuration, which is read from the environment at the
process boundary and passed down explicitly.

## Consequences

### What becomes easier

* A feature that spans both languages has one home: the contract in
  `contracts/`, the implementations on either side of it.
* The generation of stubs is a single command (`make proto`), so the two
  implementations cannot drift.
* The layout survives the arrival of a third language: a new service is a
  new directory, not a new top-level axis.
* Runtime state is out of the repository, in `var/`, and can be deleted at
  any time.

### What becomes harder

* The repository needs build tooling that spans languages — hence the
  `Makefile` as the single entrypoint, with `make` targets for both.
* Generated code has to be kept out of the tree (`.gen/`, gitignored) and
  regenerated in CI, which costs a little time on every build.
* The monorepo is only worth it while the components change together. A
  component that diverges should be split out, and that decision will have
  to be taken deliberately.

### What is now forbidden

* Defining a message that crosses a service boundary outside `contracts/`.
* A service importing from another service, or a library importing from a
  service.
* Committing runtime state, artefacts or logs.
* Adding a second build entrypoint (`build.sh`, `justfile`, …). `make` is
  the interface; everything else is a detail of a target.

## Alternatives considered

### Split into two repositories

Rejected. The two halves share a contract that changes for the same reason
at the same time. Separate repositories mean separate pull requests,
separate reviews, a versioning problem between them, and a class of bug
where one side is deployed before the other.

### Organise by language (`src/cpp`, `src/python`)

Rejected. It is the layout the repository had, and it is the reason the
original layout was replaced: a feature that touched both sides was split
across two directories with no shared context, and the contract between them
was implicit.

### A single language

Rejected. The ingestion path is latency sensitive and benefits from C++'s
control over memory and allocation; the analytics path benefits from the
numerical ecosystem of Python. Rewriting either half in the other language's
idiom would cost more than the polyglot overhead.

### Use Bazel for the whole build

Deferred, not rejected. Bazel would solve the polyglot build properly, but
it is a large operational commitment for a repository of this size. The
`Makefile` covers the same ground with far less machinery, and the
migration path stays open.
