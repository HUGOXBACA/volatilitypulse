#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# The offline end-to-end demo.
#
# It exercises the whole C++ path with no Docker, no broker and no upstream
# API key:
#
#   1. generate a synthetic option chain,
#   2. run it through the ingestion engine,
#   3. write it to the binary audit log,
#   4. read the log back and show what was recorded.
#
#   make demo
#
# This is the fastest way to confirm that the build works on your machine.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
step() { printf '\n\033[1;36m── %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m fail\033[0m %s\n' "$*" >&2; exit 1; }

SYMBOL="${SYMBOL:-AAPL}"
STRIKES="${STRIKES:-41}"
REPLAY="var/replay/${SYMBOL}.ndjson"
LOG="var/binary-logs/options.vlog"

# ── 1. Build ───────────────────────────────────────────────────────────────
step "Building the ingestion engine"
if [[ ! -x build/bin/volpulse-ingestion ]]; then
  cmake --preset dev >/dev/null
  cmake --build --preset dev >/dev/null
fi
info "build/bin/volpulse-ingestion is ready"

# ── 2. Seed ────────────────────────────────────────────────────────────────
step "Generating a synthetic option chain"
poetry -C . run python tools/scripts/seed_market_data.py \
  --symbol "${SYMBOL}" \
  --strikes "${STRIKES}" \
  --output "${REPLAY}"

# ── 3. Ingest ──────────────────────────────────────────────────────────────
step "Running the ingestion engine (replay mode)"
rm -f "${LOG}"
build/bin/volpulse-ingestion \
  --replay "${REPLAY}" \
  --binary-log "${LOG}" \
  --no-dry-run

# ── 4. Verify ─────────────────────────────────────────────────────────────
step "Reading the audit log back"
poetry -C . run python tools/scripts/inspect_log.py "${LOG}" --quotes 5

printf '\n\033[1;32m✔ demo complete\033[0m — %s quotes are in %s\n' "${STRIKES}" "${LOG}"
printf '  next: make test      run every test suite\n'
printf '        make infra-up  start the full stack (needs Docker)\n\n'
