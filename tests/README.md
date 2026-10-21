# Cross-service tests

These tests exercise the system across process boundaries: they need the
local infrastructure, and they are slower and less deterministic than the
unit suites.

| Directory | What belongs here |
| --- | --- |
| `integration/` | One service against its real dependencies: the consumer against a real broker, the writer against a real database. |
| `e2e/` | The whole pipeline: a producer, the broker, the consumer, the stores. |
| `fixtures/` | Shared input: recorded payloads, reference datasets, seeded market data. |

## Running them

```bash
make infra-up
make topics
poetry -C pyproject.toml run pytest tests -v -m integration
poetry -C pyproject.toml run pytest tests -v -m e2e
```

The markers are declared in the root `pyproject.toml`:

```toml
markers = [
    "integration: requires the local infra stack to be running",
    "e2e: full pipeline test across every service",
    "slow: long running test",
]
```

## Rules

* **A test that needs the infrastructure says so.** Use the marker; the
  default run must not require Docker.
* **Tests are idempotent.** The stores are not cleaned between runs, so a
  test must use its own key space (a unique symbol, a unique portfolio id)
  rather than assuming an empty database.
* **No sleeps.** Wait for a condition with a timeout, and fail with the
  observed state. A sleep is either flaky or slow, usually both.
* **Fixtures are recorded, not mocked.** The point of an integration test
  is the real thing. A recorded upstream payload in `fixtures/` is worth
  more than a mock that agrees with the implementation.

## What a good e2e test asserts

1. A quote produced by the C++ engine appears in the binary audit log.
2. It is published to the broker under the symbol as the key.
3. The Python consumer decodes it, validates it and writes it to
   TimescaleDB.
4. The quote can be found by (underlying, time range) in the database.

That chain is the definition of the pipeline working.
