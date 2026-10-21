#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Install the C++ dependencies.
#
# The dependency set is declared once, in vcpkg.json, and installed into a
# local manifest directory inside the repository so that the build is
# reproducible and does not depend on a globally configured vcpkg.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m warn\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m fail\033[0m %s\n' "$*" >&2; exit 1; }

command -v cmake >/dev/null 2>&1 || fail "cmake is not installed"

VCPKG_ROOT="${VCPKG_ROOT:-${ROOT}/.vcpkg}"
MANIFEST_DIR="${ROOT}/build/vcpkg_installed"

if [[ ! -d "${VCPKG_ROOT}" ]]; then
  info "cloning vcpkg into ${VCPKG_ROOT}"
  git clone https://github.com/microsoft/vcpkg.git "${VCPKG_ROOT}"
  "${VCPKG_ROOT}/bootstrap-vcpkg.sh" -disableMetrics
fi

info "installing the manifest dependencies"
"${VCPKG_ROOT}/vcpkg" install \
  --triplet="${VCPKG_TRIPLET:-arm64-osx}" \
  --x-manifest-root="${ROOT}" \
  --x-install-root="${MANIFEST_DIR}"

info "vcpkg dependencies installed into ${MANIFEST_DIR}"
warn "build with: cmake --preset dev -DCMAKE_TOOLCHAIN_FILE=${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
