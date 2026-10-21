#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap the development environment.
#
# Idempotent: run it as often as you like. It installs the Python
# workspace, the C++ dependencies and the generated protobuf stubs.
#
#   bash tools/scripts/bootstrap.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m warn\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m fail\033[0m %s\n' "$*" >&2; exit 1; }

# ── Toolchain checks ───────────────────────────────────────────────────────
for tool in python3 poetry git; do
  command -v "${tool}" >/dev/null 2>&1 || fail "${tool} is not installed"
done

info "python: $(python3 --version)"
info "poetry: $(poetry --version)"

# ── Environment file ───────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  info "creating .env from .env.example"
  cp .env.example .env
  warn ".env contains placeholder credentials; fill them in before using the upstream API"
fi

# ── Python ────────────────────────────────────────────────────────────────
info "installing the Python workspace"
poetry -C . install --no-interaction
poetry -C libs/py-core install --no-interaction
poetry -C services/analytics-py install --no-interaction

# ── C++ ───────────────────────────────────────────────────────────────────
info "installing the C++ dependencies"
bash tools/scripts/bootstrap_cpp.sh

# ── Contracts ─────────────────────────────────────────────────────────────
if command -v buf >/dev/null 2>&1; then
  info "generating the protobuf stubs"
  bash tools/scripts/codegen.sh
else
  warn "buf is not installed: skipping code generation (see https://buf.build/docs/installation)"
fi

# ── Runtime directories ───────────────────────────────────────────────────
mkdir -p var/{logs,binary-logs,checkpoints,artifacts}

info "bootstrap complete"
cat <<'EOF'

Next steps:
  make infra-up          start the local infrastructure
  make topics            create the Kafka topics
  make test              run every test suite
  make run-stack         run the ingestion and analytics services

EOF
