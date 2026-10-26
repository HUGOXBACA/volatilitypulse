# ─────────────────────────────────────────────────────────────────────────────
# Prometheus metrics for VolPulse.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import threading
import types
from dataclasses import dataclass
from typing import Self

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = __import__("logging").getLogger(__name__)

__all__ = [
    "ACTIVE_CONNECTIONS_GAUGE",
    "CACHE_HIT_RATIO",
    "ERROR_COUNTER",
    "LATENCY_HISTOGRAM",
    "THROUGHPUT_COUNTER",
    "MetricsRegistry",
    "get_metrics_registry",
]


@dataclass(frozen=True, slots=True)
class MetricLabels:
    """Standardized label names for consistency across metrics."""

    SERVICE = "service"
    ENDPOINT = "endpoint"
    METHOD = "method"
    STATUS = "status"
    ERROR_TYPE = "error_type"
    CACHE_NAME = "cache_name"
    COMPONENT = "component"


# Global registry instance
_registry: MetricsRegistry | None = None
_registry_lock = threading.Lock()


def get_metrics_registry() -> MetricsRegistry:
    """Get the global metrics registry (singleton)."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = MetricsRegistry()
    return _registry


class MetricsRegistry:
    """Centralized metrics registry for the VolPulse platform.

    Provides thread-safe access to all metrics and ensures consistent
    labeling across the platform.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or CollectorRegistry()
        self._lock = threading.Lock()

        # Latency histograms (in seconds)
        self._latency_histogram = Histogram(
            "volpulse_latency_seconds",
            "Latency of operations in seconds",
            ["service", "operation"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self._registry,
        )

        # Throughput counters
        self._throughput_counter = Counter(
            "volpulse_throughput_total",
            "Total number of processed items",
            ["service", "operation", "status"],
            registry=self._registry,
        )

        # Error counters
        self._error_counter = Counter(
            "volpulse_errors_total",
            "Total number of errors",
            ["service", "operation", "error_type"],
            registry=self._registry,
        )

        # Active connections gauge
        self._active_connections = Gauge(
            "volpulse_active_connections",
            "Number of active connections",
            ["service", "component"],
            registry=self._registry,
        )

        # Cache hit ratio
        self._cache_hits = Counter(
            "volpulse_cache_hits_total",
            "Total number of cache hits",
            ["cache_name"],
            registry=self._registry,
        )
        self._cache_misses = Counter(
            "volpulse_cache_misses_total",
            "Total number of cache misses",
            ["cache_name"],
            registry=self._registry,
        )

    # ── Latency ─────────────────────────────────────────────────────────────

    def observe_latency(self, service: str, operation: str, duration_seconds: float) -> None:
        """Record latency observation."""
        self._latency_histogram.labels(service=service, operation=operation).observe(duration_seconds)

    def get_latency_histogram(self) -> Histogram:
        """Get the latency histogram for direct use."""
        return self._latency_histogram

    # ── Throughput ──────────────────────────────────────────────────────────

    def increment_throughput(self, service: str, operation: str, status: str = "success", count: int = 1) -> None:
        """Increment throughput counter."""
        self._throughput_counter.labels(service=service, operation=operation, status=status).inc(count)

    # ── Errors ──────────────────────────────────────────────────────────────

    def increment_error(self, service: str, operation: str, error_type: str) -> None:
        """Increment error counter."""
        self._error_counter.labels(service=service, operation=operation, error_type=error_type).inc()

    # ── Connections ─────────────────────────────────────────────────────────

    def set_active_connections(self, service: str, component: str, count: int) -> None:
        """Set active connections gauge."""
        self._active_connections.labels(service=service, component=component).set(count)

    def increment_connections(self, service: str, component: str, delta: int = 1) -> None:
        """Increment active connections."""
        self._active_connections.labels(service=service, component=component).inc(delta)

    def decrement_connections(self, service: str, component: str, delta: int = 1) -> None:
        """Decrement active connections."""
        self._active_connections.labels(service=service, component=component).dec(delta)

    # ── Cache ───────────────────────────────────────────────────────────────

    def record_cache_hit(self, cache_name: str) -> None:
        """Record cache hit."""
        self._cache_hits.labels(cache_name=cache_name).inc()

    def record_cache_miss(self, cache_name: str) -> None:
        """Record cache miss."""
        self._cache_misses.labels(cache_name=cache_name).inc()

    def get_cache_hit_ratio(self, cache_name: str) -> float:
        """Calculate cache hit ratio for a cache."""
        hits = self._cache_hits.labels(cache_name=cache_name)._value.get()
        misses = self._cache_misses.labels(cache_name=cache_name)._value.get()
        total = hits + misses
        return hits / total if total > 0 else 0.0

    # ── Export ──────────────────────────────────────────────────────────────

    def generate_metrics(self) -> bytes:
        """Generate Prometheus metrics exposition format."""
        return generate_latest(self._registry)

    def get_content_type(self) -> str:
        """Get the content type for Prometheus metrics."""
        return CONTENT_TYPE_LATEST

    def get_registry(self) -> CollectorRegistry:
        """Get the underlying Prometheus registry."""
        return self._registry


# ── Pre-created default metrics for convenience ─────────────────────────────

LATENCY_HISTOGRAM = Histogram(
    "volpulse_latency_seconds",
    "Latency of operations in seconds",
    ["service", "operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

THROUGHPUT_COUNTER = Counter(
    "volpulse_throughput_total",
    "Total number of processed items",
    ["service", "operation", "status"],
)

ERROR_COUNTER = Counter(
    "volpulse_errors_total",
    "Total number of errors",
    ["service", "operation", "error_type"],
)

ACTIVE_CONNECTIONS_GAUGE = Gauge(
    "volpulse_active_connections",
    "Number of active connections",
    ["service", "component"],
)

CACHE_HIT_RATIO = Gauge(
    "volpulse_cache_hit_ratio",
    "Cache hit ratio",
    ["cache_name"],
)


# ─── Helper functions ───────────────────────────────────────────────────────

class LatencyTimer:
    """Context manager for timing operations."""

    def __init__(self, registry: MetricsRegistry, service: str, operation: str) -> None:
        self._registry = registry
        self._service = service
        self._operation = operation
        self._start_time: float = 0.0

    def __enter__(self) -> Self:
        import time
        self._start_time = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        import time
        duration = time.perf_counter() - self._start_time
        self._registry.observe_latency(self._service, self._operation, duration)