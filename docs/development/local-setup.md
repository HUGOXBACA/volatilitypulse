# Environment reference

The details of the development environment: how the dependencies are
managed, what the environment variables mean, and how to fix a broken
setup. For the ten-minute path, read
[getting-started.md](getting-started.md) first.

---

## The toolchain

| Tool | Version | Managed by | Used for |
| --- | --- | --- | --- |
| Python | 3.12 – 3.14 | Homebrew or python.org | The analytics engine, the shared library, the tooling. |
| Poetry | 2.x | `pipx` or Homebrew | Every Python dependency. |
| CMake | 3.24+ | Homebrew | The C++ workspace. |
| Ninja | any | Homebrew | The CMake generator. |
| A C++20 compiler | Clang 16+ / GCC 12+ | Xcode CLT | The ingestion engine. |
| vcpkg | latest | `brew install vcpkg` | The C++ dependencies. |
| buf | 1.4x+ | Homebrew | Contract linting and code generation. |
| clang-format | any | Homebrew | The C++ format gate. |
| Docker | any | Docker Desktop | The local infrastructure only. |

Nothing in the repository requires a specific Python patch release. The
constraint `>=3.12,<3.15` exists because the numerical stack (NumPy, SciPy,
pandas) publishes wheels for those versions.

---

## How the Python dependencies are managed

There are **three** Poetry projects, and each has its own lock file:

| Project | Package | Lock file | Contains |
| --- | --- | --- | --- |
| `.` (the root) | none — `package-mode = false` | `poetry.lock` | The workspace: every runtime dependency plus the tooling. |
| `libs/py-core` | `volpulse-core` | `libs/py-core/poetry.lock` | The shared library. |
| `services/analytics-py` | `volpulse-analytics` | `services/analytics-py/poetry.lock` | The analytics service. |

The root project ships no importable package: it exists so that one
`poetry install` gives a developer everything needed to run the tests and
the tools. The two member packages are what would be published.

The service depends on the library by path, not by version:

```toml
[tool.poetry.dependencies]
volpulse-core = { path = "../../libs/py-core", develop = true }
```

The two halves of the Python stack change together, so they are versioned
together.

### The command that keeps working

```bash
poetry -C <directory> <command>
```

`-C` takes a **directory**. `poetry -C pyproject.toml` is wrong and fails
with *"Specified path 'pyproject.toml' is not a valid directory"*.

### The lock files

All three lock files are committed. After changing a dependency:

```bash
poetry -C . lock && poetry -C . install
```

Commit the lock file with the change. A dependency bump is a change to the
product, and it is reviewed like one — `dependabot.yml` proposes them on a
schedule.

### The acceleration extra

`numba` and `jax` are declared but not installed by default: they pull in
large binary wheels and nothing imports them yet. They are the first
acceleration step described in
[ADR 0004](../adr/0004-accelerator-deferral.md).

```bash
poetry -C . install --extras accelerate
```

---

## How the C++ dependencies are managed

`vcpkg.json` is the manifest. It lists the packages and pins the versions
through the `builtin-baseline` commit:

```json
{
  "name": "volpulse-cpp",
  "builtin-baseline": "857036234d15fbed8f30fed66e898d7725446c0c",
  "dependencies": ["protobuf", "grpc", "librdkafka", "curl", "openssl",
                   "nlohmann-json", "spdlog"]
}
```

The baseline is what makes the build reproducible. Do not add
`"version>="` constraints without checking that the minimum version exists
in the baseline's version database — vcpkg rejects the manifest otherwise.

```bash
bash tools/scripts/bootstrap_cpp.sh     # install into build/vcpkg_installed
```

The install directory is inside the repository and is gitignored. The
`Makefile` passes the toolchain file to CMake automatically when
`.vcpkg/` exists, so `make build-cpp` just works.

---

## The environment variables

`.env` is gitignored. `.env.example` is the committed contract and lists
every variable with its default. Copy it and fill it in:

```bash
cp .env.example .env
```

The variables are read **once**, at the process boundary, by
`volpulse_core.config.load_settings()`, and then passed down explicitly. No
module reads `os.environ` outside that function.

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `IVOL_API_KEY` | **yes** | — | The upstream API key. The services refuse to start without it. |
| `IVOL_BASE_URL` | no | `https://api.ivolatility.com` | The upstream. |
| `IVOL_RATE_LIMIT_RPS` | no | `1.0` | The upstream quota. **Do not raise it.** |
| `IVOL_MAX_CONCURRENCY` | no | `4` | Simultaneous upstream calls. |
| `KAFKA_BOOTSTRAP_SERVERS` | no | `localhost:9092` | The broker. |
| `KAFKA_TOPIC_OPTIONS` | no | `options.chain.streaming` | The quote topic. |
| `KAFKA_CONSUMER_GROUP` | no | `volpulse-analytics` | The consumer group. |
| `TIMESCALE_*` | no | localhost | The time-series store. |
| `POSTGRES_*` | no | localhost | The relational store. |
| `PROMETHEUS_URL`, `INFLUXDB_URL`, `SENSU_URL` | no | localhost | The monitoring stack. |
| `LOG_LEVEL`, `LOG_FORMAT` | no | `INFO`, `json` | Logging. |
| `BINARY_LOG_DIR`, `CHECKPOINT_DIR`, `ARTIFACT_DIR` | no | `var/…` | Runtime paths. |

Secrets are never logged. The redaction list in `config/logging.yaml` is
binding.

---

## The runtime directories

Everything under `var/` is runtime state and is gitignored:

```
var/
├── logs/         structured application logs
├── binary-logs/  the audit log
├── checkpoints/  ingestion checkpoints
├── artifacts/    Parquet and NPZ artefacts
├── kafka/        local broker data
└── db/           local database data
```

Delete `var/` at any time. It is rebuilt by `make bootstrap` and by the
services.

---

## The generated code

`contracts/` is the source of truth; `.gen/` holds the generated stubs and
is gitignored.

```bash
make proto          # buf lint, then generate into .gen/
```

| Language | Output | Import as |
| --- | --- | --- |
| Python | `.gen/python` | `volpulse.options.v1.quote_pb2` |
| C++ | `.gen/cpp` | `volpulse/options/v1/quote.pb.h` |

The Python stubs are not on the path by default. Add them:

```bash
export PYTHONPATH="$PWD/.gen/python:$PWD/libs/py-core/src:$PWD/services/analytics-py/src"
```

`make test` does this for you, which is why the contract tests run without
any setup.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Specified path 'pyproject.toml' is not a valid directory` | `poetry -C` was given a file | Use `poetry -C .` |
| `ruff-lsp requires Python >=3.7,<3.12` | The dependency list is stale | `poetry -C . lock && poetry -C . install` |
| `no versions match numba/numpy` | Conflicting pins | `poetry -C . lock` after loosening the constraint |
| `No module named '_cffi_backend'` | A broken Poetry install | `pipx reinstall poetry` |
| `vcpkg.json was rejected ... "builtin-baseline"` | The manifest lost its baseline | `git checkout vcpkg.json` |
| `buf: command not found` | Codegen skipped | `brew install buf && make proto` |
| `clang-format: No such file` | The C++ format gate skipped | `brew install clang-format` |
| `docker: command not found` | The full stack cannot start | Install Docker Desktop, or use `make demo` |
| Ports 9092/5432/9090 in use | Another service holds them | Stop it, or change the port in `docker-compose.yml` |
| `poetry` picks up the wrong interpreter | A stale venv | `poetry -C . env use 3.12` |

---

## Where things are

```bash
make tree
```

The tree is generated from the filesystem, so it cannot drift from reality.
If it does not answer *"where does this live?"*, that is a bug in the
layout — and the fix belongs in the layout, not in a note.
