# Getting started

Everything below has been run end to end on a clean checkout. If a command
here does not do what it says, that is a bug in the repository, not in your
setup.

**Time to first working pipeline: about ten minutes**, and it needs no
Docker and no API key.

---

## 0. Prerequisites

| Tool | Version | Needed for | Install |
| --- | --- | --- | --- |
| Python | 3.12 – 3.14 | The analytics engine | `brew install python@3.12` |
| Poetry | 2.x | Dependency management | `pipx install poetry` or `brew install poetry` |
| CMake | 3.24+ | The C++ workspace | `brew install cmake` |
| Ninja | any | The CMake generator | `brew install ninja` |
| A C++20 compiler | Clang 16+ / GCC 12+ | The ingestion engine | `xcode-select --install` |
| vcpkg | latest | The C++ dependencies | `brew install vcpkg` |
| buf | 1.4x+ | Protobuf lint and codegen | `brew install buf` |
| clang-format | any | The C++ format check | `brew install clang-format` |
| Docker | any | The **full** stack only | <https://docs.docker.com/desktop/install/mac-install/> |

Check what you have:

```bash
python3 --version && poetry --version && cmake --version \
  && ninja --version && buf --version && clang-format --version
```

> **Poetry 2.x is required.** Poetry 1.x does not understand the PEP 621
> `[project]` tables this repository uses.

---

## 1. Bootstrap

```bash
cd /Users/user0001/Projects/volatilitypulse
bash tools/scripts/bootstrap.sh
```

This is idempotent — run it whenever you are unsure. It:

1. checks the toolchain and prints the versions,
2. creates `.env` from `.env.example` if it does not exist,
3. installs the Python workspace and the two Python packages (`poetry install`),
4. installs the C++ dependencies into `build/vcpkg_installed` from `vcpkg.json`,
5. generates the protobuf stubs into `.gen/`,
6. creates the runtime directories under `var/`.

The vcpkg step is the slow one (a few minutes the first time, seconds after
that, because the binaries are cached).

**Check it worked:**

```bash
poetry -C . run python -c "import numpy, scipy, polars, pandas; print('python ok')"
ls .gen/python/volpulse/options/v1/
```

---

## 2. Run the demo — no Docker, no API key

```bash
make demo
```

This is the fastest way to confirm the whole build works. It:

1. builds the C++ ingestion engine,
2. generates a synthetic option chain (41 quotes around AAPL),
3. runs it through the ingestion engine in replay mode,
4. writes it to the binary audit log,
5. reads the log back and prints what was recorded.

Expected output:

```
── Generating a synthetic option chain
wrote 41 quotes to var/replay/AAPL.ndjson

── Running the ingestion engine (replay mode)
ingestion complete: 41 quotes in 1 batches, 0.000139208s, audit log var/binary-logs/options.vlog

── Reading the audit log back
file        : var/binary-logs/options.vlog
size        : 5,576 bytes
records     : 41
valid bytes : 5,576
tail        : clean
sequence    : 0..40
time span   : 0.040s
symbols     : AAPL
strike range: 121.88 .. 253.12

first 5 quotes:
  AAPL   AAPL-30-0000         K=  121.88 bid=  75.03 ask=  76.55 iv=0.4743
  ...
```

If that prints, the C++ build, the Python environment and the binary log
format all work.

---

## 3. Run the tests

```bash
make test
```

* **46 Python tests** — unit tests plus `hypothesis` property tests for the
  pricing model and the surface fitter, plus the protobuf contract
  round-trip.
* **2 C++ test binaries** — 57 assertions covering the binary log (framing,
  CRC, torn-tail healing, growth) and the ingestion pipeline.

```
46 passed in 0.70s
100% tests passed out of 2
```

---

## 4. Run the quality gates

```bash
make lint
```

Runs `ruff check`, `ruff format --check`, `mypy --strict`, `clang-format`
and `buf lint` + `buf format`. All five must pass; CI runs the same ones.

---

## 5. (Optional) Run the full stack

This part needs Docker. Start the infrastructure:

```bash
make infra-up        # Kafka, TimescaleDB, Postgres, Prometheus, Grafana…
make topics          # create the Kafka topics with the right retention
```

Then run both services:

```bash
make run-stack
```

| Service | URL |
| --- | --- |
| Grafana | <http://localhost:3000> (`admin` / `admin`) |
| Prometheus | <http://localhost:9090> |
| Kafka | `localhost:9092` |
| TimescaleDB | `localhost:5432` |
| PostgreSQL | `localhost:5433` |
| InfluxDB | <http://localhost:8086> |
| Analytics metrics | <http://localhost:9100/metrics> |

To use the real upstream, put your key in `.env`:

```bash
cp .env.example .env
$EDITOR .env        # set IVOL_API_KEY
```

The quota is roughly one request per second. `IVOL_RATE_LIMIT_RPS` defaults
to `1.0` and must not be raised.

---

## 6. Where to go next

| I want to… | Read |
| --- | --- |
| Use a specific component | [usage.md](usage.md) |
| Understand the system | [../architecture/overview.md](../architecture/overview.md) |
| Change something safely | [../architecture/data-flow.md](../architecture/data-flow.md) |
| Know why it is built this way | [../adr/](../adr/) |
| Fix an alert | [../runbooks/](../runbooks/) |
| Set up the environment in detail | [local-setup.md](local-setup.md) |

## If something goes wrong

| Symptom | Cause | Fix |
| --- | --- | --- |
| `poetry: command not found` | Poetry not installed | `pipx install poetry` |
| `Specified path 'pyproject.toml' is not a valid directory` | An old `poetry -C pyproject.toml` | Use `poetry -C .` — `-C` takes a directory |
| `ruff-lsp requires Python >=3.7,<3.12` | Stale dependency list | `poetry -C . lock && poetry -C . install` |
| `vcpkg.json was rejected ... "builtin-baseline"` | The manifest lost its baseline | `git checkout vcpkg.json` |
| `buf is not installed` | Codegen skipped | `brew install buf && make proto` |
| `No module named '_cffi_backend'` | A broken Poetry install | `pipx reinstall poetry` |
| Ports already in use | Another service holds 9092/5432/9090 | Stop it, or change the port in `docker-compose.yml` |
