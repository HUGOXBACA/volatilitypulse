# Local setup

Everything below runs on a clean macOS (or Linux) machine with Python 3.12+
and a C++20 compiler.

## Prerequisites

| Tool | Version | Used for |
| --- | --- | --- |
| Python | 3.12 – 3.14 | The analytics engine and the shared library. |
| Poetry | 2.x | Dependency management. |
| CMake | 3.24+ | The C++ workspace. |
| Ninja | any | The CMake generator. |
| A C++20 compiler | Clang 16+ / GCC 12+ | The ingestion engine. |
| vcpkg | latest | The C++ dependencies. |
| buf | 1.4x+ | Protobuf linting and code generation. |
| Docker | any | The local infrastructure. |

On macOS:

```bash
brew install python@3.12 poetry cmake ninja vcpkg buf
```

## Bootstrap

```bash
git clone <repository> && cd volatilitypulse
bash tools/scripts/bootstrap.sh
```

The bootstrap is idempotent. It:

1. checks the toolchain and prints the versions,
2. creates `.env` from `.env.example` if it does not exist,
3. installs the Python workspace and the two Python packages,
4. installs the C++ dependencies into `build/vcpkg_installed` from
   `vcpkg.json`,
5. generates the protobuf stubs into `.gen/`,
6. creates the runtime directories under `var/`.

## Configuration

`.env` holds the environment. It is gitignored; `.env.example` is the
contract and is committed.

```bash
cp .env.example .env
$EDITOR .env          # at minimum: IVOL_API_KEY
```

The variable that matters most is `IVOL_API_KEY`. The upstream subscription
is metered at roughly one request per second — `IVOL_RATE_LIMIT_RPS`
defaults to `1.0` and must not be raised.

## The local infrastructure

```bash
make infra-up          # start everything, wait until it is healthy
make topics            # create the Kafka topics
make infra-logs        # tail it
make infra-down        # stop it
make infra-reset       # stop it and delete the volumes
```

What runs:

| Service | Port | Purpose |
| --- | --- | --- |
| Kafka | 9092 | The message broker (KRaft mode). |
| TimescaleDB | 5432 | The time-series store. |
| PostgreSQL | 5433 | The relational store. |
| Prometheus | 9090 | Metrics and alerting rules. |
| Grafana | 3000 | Dashboards (`admin` / `admin` by default). |
| InfluxDB | 8086 | Long-horizon metrics. |
| Sensu | 8080 | Alert dispatch. |

Artifactory is behind an opt-in profile, because it is heavy:

```bash
docker compose --profile artifactory up -d
```

## Running the pipeline

### Without upstream access

The replay path exercises the whole pipeline without spending quota:

```bash
python tools/scripts/seed_market_data.py \
  --symbol AAPL --output var/replay/aapl.ndjson

build/bin/volpulse-ingestion \
  --replay var/replay/aapl.ndjson \
  --binary-log var/binary-logs/options.vlog \
  --no-dry-run
```

The quotes land in the binary audit log. Read them back with the reader, or
check the file size: it is exactly the size of the records, because the
writer trims the file to its logical size when it closes.

### With upstream access

```bash
make run-stack
```

This starts the analytics engine and the ingestion engine together. The
analytics engine needs the generated stubs, so the script generates them if
they are missing.

## Tests

```bash
make test           # everything
make test-py        # pytest, including the property tests
make test-cpp       # ctest
```

The Python property tests use `hypothesis`; they generate thousands of
cases, so the first run takes noticeably longer than the second (Hypothesis
caches the failures it has seen).

## Linting and formatting

```bash
make lint           # ruff, mypy --strict, clang-format, buf lint
make format         # apply the fixes
```

`mypy` runs in strict mode and `buf lint` runs the standard rule set. Both
are enforced in CI, so a green local run and a green CI mean the same thing.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `make install-py` fails on Python 3.14 | Some wheels are not published yet. | Use 3.12 or 3.13. |
| CMake cannot find protobuf | vcpkg was not bootstrapped. | `bash tools/scripts/bootstrap_cpp.sh`. |
| `buf` is not found | The code generator is missing. | `brew install buf`, then `make proto`. |
| Kafka topics are missing | The broker does not auto-create them. | `make topics`. |
| `IVOL_API_KEY` errors | The placeholder is still in `.env`. | Fill it in. |
| Ports already in use | Something else is using 9092/5432/9090. | Stop it, or change the port in `docker-compose.yml`. |

## Where things are

```bash
make tree            # the layout, generated from the filesystem
```

If the tree does not answer "where does this live?", that is a bug in the
tree, and the fix belongs in the layout — not in a note.
