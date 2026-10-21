"""Prometheus metrics for the VolPulse pipeline.

Every service owns its own registry so that a test can instantiate the
metrics without colliding with the global default registry.

The metric names below are part of the operational contract: dashboards in
``infra/grafana`` and the alerting rules in ``infra/prometheus/rules`` query
them by name. Renaming one is a breaking change for the on-call rotation.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

__all__ = ["VolPulseMetrics"]


class VolPulseMetrics:
    """The metric set exported by the VolPulse services."""

    __slots__ = (
        "consumer_lag",
        "end_to_end_latency",
        "greek_calculations",
        "persistence_write_duration",
        "quotes_consumed",
        "quotes_dropped",
        "registry",
        "surface_arbitrage_violations",
        "surface_fit_duration",
        "surface_fit_rms_error",
        "upstream_pacing_delay",
        "upstream_request_duration",
    )

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Create the metric set.

        Args:
            registry: Registry to register into. A fresh registry is created
                when omitted, which keeps tests isolated from each other.
        """
        self.registry = registry if registry is not None else CollectorRegistry()

        self.quotes_consumed = Counter(
            "volpulse_quotes_consumed_total",
            "Quotes successfully consumed from the broker.",
            labelnames=("underlying",),
            registry=self.registry,
        )
        self.quotes_dropped = Counter(
            "volpulse_quotes_dropped_total",
            "Quotes dropped by the consumer.",
            labelnames=("underlying", "reason"),
            registry=self.registry,
        )
        self.consumer_lag = Gauge(
            "volpulse_consumer_lag_seconds",
            "Age of the oldest record sitting in the broker partition.",
            labelnames=("topic", "partition"),
            registry=self.registry,
        )
        self.end_to_end_latency = Histogram(
            "volpulse_end_to_end_latency_seconds",
            "Time from upstream event timestamp to analytics processing.",
            labelnames=("underlying",),
            buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0),
            registry=self.registry,
        )
        self.upstream_request_duration = Histogram(
            "volpulse_upstream_request_duration_seconds",
            "Duration of upstream API calls.",
            labelnames=("endpoint",),
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 15.0),
            registry=self.registry,
        )
        self.upstream_pacing_delay = Gauge(
            "volpulse_upstream_pacing_delay_seconds",
            "Seconds the upstream client is currently holding back.",
            registry=self.registry,
        )
        self.surface_fit_duration = Histogram(
            "volpulse_surface_fit_duration_seconds",
            "Time spent fitting an implied volatility surface.",
            labelnames=("underlying",),
            buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
            registry=self.registry,
        )
        self.surface_fit_rms_error = Gauge(
            "volpulse_surface_fit_rms_error",
            "RMS error of the most recent surface fit.",
            labelnames=("underlying",),
            registry=self.registry,
        )
        self.surface_arbitrage_violations = Counter(
            "volpulse_surface_arbitrage_violations_total",
            "Number of detected butterfly or calendar arbitrage violations.",
            labelnames=("underlying", "kind"),
            registry=self.registry,
        )
        self.persistence_write_duration = Histogram(
            "volpulse_persistence_write_duration_seconds",
            "Time spent writing analytics results to the stores.",
            labelnames=("store",),
            buckets=(0.005, 0.05, 0.25, 1.0, 5.0),
            registry=self.registry,
        )
        self.greek_calculations = Counter(
            "volpulse_greek_calculations_total",
            "Number of Greek evaluations performed.",
            labelnames=("underlying",),
            registry=self.registry,
        )

    def render(self) -> bytes:
        """Render the registry in the Prometheus text exposition format."""
        return generate_latest(self.registry)
