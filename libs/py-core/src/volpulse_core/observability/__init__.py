# ─────────────────────────────────────────────────────────────────────────────
# VolPulse Observability — Prometheus metrics, structured logging, health.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from .health import HealthCheck, HealthCheckRegistry, HealthStatus, get_health_registry
from .logging import LogContext, get_logger, setup_logging
from .metrics import (
    ACTIVE_CONNECTIONS_GAUGE,
    CACHE_HIT_RATIO,
    ERROR_COUNTER,
    LATENCY_HISTOGRAM,
    THROUGHPUT_COUNTER,
    MetricsRegistry,
    get_metrics_registry,
)

__all__ = [
    "ACTIVE_CONNECTIONS_GAUGE",
    "CACHE_HIT_RATIO",
    "ERROR_COUNTER",
    "LATENCY_HISTOGRAM",
    "THROUGHPUT_COUNTER",
    "HealthCheck",
    "HealthCheckRegistry",
    "HealthStatus",
    "LogContext",
    "MetricsRegistry",
    "get_health_registry",
    "get_logger",
    "get_metrics_registry",
    "setup_logging",
]