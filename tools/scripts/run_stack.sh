#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Run the ingestion and analytics services together.
#
# The analytics engine needs the generated protobuf stubs, so the script
# generates them when they are missing. It fails loudly rather than
# starting a service that cannot decode anything.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m fail\033[0m %s\n' "$*" >&2; exit 1; }

if [[ ! -d .gen/python ]]; then
  info "generating the protobuf stubs"
  bash tools/scripts/codegen.sh
fi

if [[ ! -x build/bin/volpulse-ingestion ]]; then
  info "building the ingestion engine"
  cmake --preset dev >/dev/null
  cmake --build --preset dev >/dev/null
fi

cleanup() {
  if [[ -n "${ANALYTICS_PID:-}" ]]; then
    kill "${ANALYTICS_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

info "starting the analytics engine"
PYTHONPATH=".gen/python:libs/py-core/src:services/analytics-py/src" \
  poetry -C services/analytics-py run python -m volpulse_analytics \
  --metrics-port 9100 &
ANALYTICS_PID=$!

info "starting the ingestion engine"
build/bin/volpulse-ingestion --config config/ingestion.conf

wait "${ANALYTICS_PID}"
