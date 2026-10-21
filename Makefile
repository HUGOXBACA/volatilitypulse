# ─────────────────────────────────────────────────────────────────────────────
# VolPulse — single entrypoint for every task in the polyglot monorepo.
# Run `make help` for the target catalogue.
#
# Design rule: contributors must never need to know whether a target lives in
# Python or C++. Every workflow is expressed here and delegated to the
# per-language toolchains (poetry, cmake, buf, docker).
# ─────────────────────────────────────────────────────────────────────────────

SHELL := /bin/bash
.DEFAULT_GOAL := help

PY_ROOT      := .
PY_LIB       := libs/py-core
PY_SERVICE   := services/analytics-py
PROTO_DIR    := contracts
GEN_DIR      := .gen
BUILD_DIR    := build
VAR_DIR      := var

# vcpkg is optional: the core C++ library has no third-party dependencies.
# When the manifest has been installed, the toolchain file is passed to CMake
# so that the build finds protobuf, gRPC and the rest.
VCPKG_DIR       := $(CURDIR)/.vcpkg
VCPKG_TOOLCHAIN := $(VCPKG_DIR)/scripts/buildsystems/vcpkg.cmake
ifneq ($(wildcard $(VCPKG_TOOLCHAIN)),)
  VCPKG_FLAGS := -DCMAKE_TOOLCHAIN_FILE=$(VCPKG_TOOLCHAIN) \
                 -DVCPKG_MANIFEST_DIR=$(CURDIR) \
                 -DVCPKG_INSTALLED_DIR=$(CURDIR)/$(BUILD_DIR)/vcpkg_installed
else
  VCPKG_FLAGS :=
endif

# Local infra compose project (namespaced so it never collides with other work).
COMPOSE      := docker compose -p volpulse
COMPOSE_FILE := docker-compose.yml

# ── Colors (disabled when piped / non-tty) ─────────────────────────────────
ifneq (,$(findstring xterm,$(TERM)))
  C_RESET := \033[0m
  C_BOLD  := \033[1m
  C_BLUE  := \033[34m
  C_GREEN := \033[32m
  C_YELL  := \033[33m
else
  C_RESET :=
  C_BOLD  :=
  C_BLUE  :=
  C_GREEN :=
  C_YELL  :=
endif

.PHONY: help
help: ## Show this catalogue
	@printf "$(C_BOLD)VolPulse$(C_RESET) — make targets\n\n"
	@grep -hE '^[a-zA-Z0-9_.-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | sort \
	  | awk 'BEGIN {FS = ":.*?## "} {printf "  $(C_BLUE)%-22s$(C_RESET) %s\n", $$1, $$2}'
	@printf "\n$(C_YELL)Tip:$(C_RESET) run 'make bootstrap' once, then 'make test'.\n"

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: bootstrap
bootstrap: ## Install all toolchains, dependencies and generated code
	@bash tools/scripts/bootstrap.sh

.PHONY: install
install: install-py install-cpp ## Install dependencies for every language

.PHONY: install-py
install-py: ## Install Python workspace + member packages
	poetry -C $(PY_ROOT) install --no-interaction
	poetry -C $(PY_LIB) install --no-interaction
	poetry -C $(PY_SERVICE) install --no-interaction

.PHONY: install-cpp
install-cpp: ## Fetch C++ dependencies (vcpkg) and configure CMake
	@bash tools/scripts/bootstrap_cpp.sh

# ─────────────────────────────────────────────────────────────────────────────
# Code generation (contracts are the source of truth)
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: proto
proto: ## Generate protobuf/gRPC stubs for C++ and Python
	@bash tools/scripts/codegen.sh

.PHONY: proto-lint
proto-lint: ## Lint protobuf contracts
	buf lint $(PROTO_DIR)
	buf format --diff --exit-code $(PROTO_DIR)

.PHONY: proto-breaking
proto-breaking: ## Detect breaking changes against the committed contracts
	buf breaking $(PROTO_DIR) --against '.git#branch=main'

# ─────────────────────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: build
build: build-cpp build-py ## Build every language

.PHONY: build-cpp
build-cpp: ## Build the C++ ingestion service and shared libraries
	cmake --preset dev $(VCPKG_FLAGS)
	cmake --build --preset dev

.PHONY: build-py
build-py: ## Byte-compile and install the Python packages
	poetry -C $(PY_ROOT) run python -m compileall -q $(PY_LIB)/src $(PY_SERVICE)/src

# ─────────────────────────────────────────────────────────────────────────────
# Quality gates
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: test
test: test-py test-cpp ## Run every test suite

.PHONY: test-py
stubs: ## Generate the protobuf stubs if they are missing
	@if [ -d "$(GEN_DIR)/python" ]; then exit 0; fi
	@command -v buf >/dev/null 2>&1 || { \
	  printf 'buf is not installed: skipping stub generation\n'; exit 0; }
	@$(MAKE) proto

test-py: stubs ## Run pytest (unit + integration + hypothesis property tests)
	PYTHONPATH="$(CURDIR)/$(GEN_DIR)/python:$(CURDIR)/$(PY_LIB)/src:$(CURDIR)/$(PY_SERVICE)/src" \
	  poetry -C $(PY_ROOT) run pytest \
	    $(PY_LIB)/tests $(PY_SERVICE)/tests $(PY_ROOT)/tests -v

.PHONY: test-cpp
test-cpp: ## Run C++ unit tests via ctest
	ctest --preset dev --output-on-failure

.PHONY: lint
lint: lint-py lint-cpp lint-proto ## Lint every language

.PHONY: lint-py
lint-py: ## ruff lint + format check, mypy strict
	poetry -C $(PY_ROOT) run ruff check $(PY_LIB) $(PY_SERVICE)
	poetry -C $(PY_ROOT) run ruff format --check $(PY_LIB) $(PY_SERVICE)
	poetry -C $(PY_ROOT) run mypy --strict $(PY_LIB)/src $(PY_SERVICE)/src

.PHONY: lint-cpp
lint-proto: ## Lint the protobuf contracts (skipped when buf is not installed)
	@command -v buf >/dev/null 2>&1 || { \
	  printf 'buf is not installed: skipping the contract lint\n'; \
	  exit 0; \
	}
	buf lint $(PROTO_DIR)
	buf format --diff --exit-code $(PROTO_DIR)

lint-cpp: ## clang-format check (skipped when clang-format is not installed)
	@command -v clang-format >/dev/null 2>&1 || { \
	  printf 'clang-format is not installed: skipping the C++ format check\n'; \
	  exit 0; \
	}
	@find libs/cpp-core services/ingestion-cpp \( -name '*.cpp' -o -name '*.h' \) -print0 \
	  | xargs -0 clang-format --dry-run --Werror

.PHONY: format
format: ## Auto-format all sources
	poetry -C $(PY_ROOT) run ruff format $(PY_LIB) $(PY_SERVICE)
	poetry -C $(PY_ROOT) run ruff check --fix $(PY_LIB) $(PY_SERVICE)
	@find libs/cpp-core services/ingestion-cpp -name '*.cpp' -o -name '*.h' \
	  | xargs clang-format -i
	buf format -w $(PROTO_DIR)

# ─────────────────────────────────────────────────────────────────────────────
# Local infrastructure
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: infra-up
infra-up: ## Start the local infra stack (Kafka, Timescale, Prometheus, ...)
	$(COMPOSE) -f $(COMPOSE_FILE) up -d --wait

.PHONY: infra-down
infra-down: ## Stop the local infra stack
	$(COMPOSE) -f $(COMPOSE_FILE) down

.PHONY: infra-reset
infra-reset: ## Stop the stack and destroy all local volumes
	$(COMPOSE) -f $(COMPOSE_FILE) down -v

.PHONY: infra-logs
infra-logs: ## Tail local infra logs
	$(COMPOSE) -f $(COMPOSE_FILE) logs -f --tail=100

.PHONY: topics
topics: ## Create Kafka topics with the configured retention policy
	@bash infra/kafka/topics.sh

# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: run-ingestion
run-ingestion: ## Run the C++ ingestion engine
	$(BUILD_DIR)/bin/volpulse-ingestion --config config/ingestion.yaml

.PHONY: run-analytics
run-analytics: ## Run the Python quant analytics engine
	poetry -C $(PY_SERVICE) run python -m volpulse_analytics --config config/analytics.yaml

.PHONY: run-stack
run-stack: ## Run ingestion + analytics in the foreground
	@bash tools/scripts/run_stack.sh

# ─────────────────────────────────────────────────────────────────────────────
# Housekeeping
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: clean
clean: ## Remove build artefacts and caches
	rm -rf $(BUILD_DIR) $(GEN_DIR)
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis

.PHONY: clean-all
clean-all: clean infra-reset ## Remove build artefacts, caches and local volumes

.PHONY: demo
demo: ## Run the offline end-to-end demo (no Docker, no API key)
	@bash tools/scripts/demo.sh

.PHONY: bench
bench: ## Run every benchmark (C++ and Python)
	@cmake --build --preset dev --target volpulse_benchmarks >/dev/null 2>&1 || true
	@echo "=== C++ benchmarks ==="
	@ctest --preset dev -R cpp.benchmarks --output-on-failure
	@echo
	@echo "=== Python benchmarks ==="
	@PYTHONPATH="$(CURDIR)/.gen/python:$(CURDIR)/$(PY_LIB)/src:$(CURDIR)/$(PY_SERVICE)/src" \
	  poetry -C $(PY_ROOT) run python services/analytics-py/tests/benchmarks/run_benchmarks.py

.PHONY: inspect-log
inspect-log: ## Inspect a binary audit log (LOG=path to override)
	poetry -C $(PY_ROOT) run python tools/scripts/inspect_log.py \
	  $(if $(LOG),$(LOG),var/binary-logs/options.vlog)

.PHONY: seed
seed: ## Generate a synthetic chain for the replay path
	poetry -C $(PY_ROOT) run python tools/scripts/seed_market_data.py \
	  --output var/replay/aapl.ndjson

.PHONY: tree
tree: ## Print the repository layout
	@bash tools/scripts/tree.sh
