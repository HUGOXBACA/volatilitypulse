#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Print the repository layout.
#
# The tree is the fastest way to answer "where does this live?" — it is
# generated from the filesystem, so it can never drift from reality.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

if command -v tree >/dev/null 2>&1; then
  tree \
    -a \
    -I '.git|node_modules|__pycache__|.venv|venv|build|.gen|*.egg-info|.mypy_cache|.pytest_cache|.ruff_cache|.hypothesis|.DS_Store|var' \
    --dirsfirst \
    -L 4 \
    "$@"
else
  find . \
    -not -path './.git/*' \
    -not -path './build/*' \
    -not -path './.gen/*' \
    -not -path './var/*' \
    -not -path '*/__pycache__*' \
    -not -path '*/node_modules/*' \
    -not -name '.DS_Store' \
    -maxdepth 4 \
    | sort
fi
