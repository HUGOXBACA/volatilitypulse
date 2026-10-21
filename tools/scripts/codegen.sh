#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Generate the protobuf and gRPC stubs.
#
# The contracts in `contracts/` are the single source of truth. The
# generated code lands in `.gen/` (gitignored) and is never edited by hand.
#
#   bash tools/scripts/codegen.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m fail\033[0m %s\n' "$*" >&2; exit 1; }

command -v buf >/dev/null 2>&1 || fail "buf is not installed (https://buf.build/docs/installation)"

info "linting the contracts"
buf lint contracts

info "generating the stubs into .gen/"
rm -rf .gen
buf generate

info "generated:"
find .gen -name '*_pb2.py' -o -name '*.pb.cc' -o -name '*.pb.h' | head -20

info "done. Add .gen/python to PYTHONPATH to use the Python stubs:"
echo "  export PYTHONPATH=\${PYTHONPATH}:$(pwd)/.gen/python"
