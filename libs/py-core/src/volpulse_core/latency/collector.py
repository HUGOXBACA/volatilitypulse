# ─────────────────────────────────────────────────────────────────────────────
# High-resolution latency sampling.
#
# Uses ``time.perf_counter_ns`` (monotonic, highest available resolution) to
# measure the wall-clock latency of an arbitrary callable. Sampling is done in
# a tight loop with no I/O between samples so that the measured cost is the
# call itself, not the harness.
#
# Design notes:
#   * ``perf_counter_ns`` is preferred over ``perf_counter`` because it
#     avoids float rounding on sub-microsecond durations.
#   * A warm-up phase runs the callable before timing begins so that CPU
#     frequency scaling, interpreter JIT effects and cold cache misses are
#     amortized rather than measured.
#   * Outliers are *not* dropped by default: a latency measurement that
#     silently discards tail events produces an optimistic and misleading
#     picture. Outlier detection is available separately
#     (:func:`volpulse_core.latency.analysis.detect_outliers`).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

__all__ = ["LatencyCollector", "Sample"]


@dataclass(frozen=True, slots=True)
class Sample:
    """A single latency measurement."""

    func_name: str
    """Qualified name of the measured callable."""
    latency_ns: int
    """Wall-clock latency in nanoseconds."""
    iteration: int
    """Zero-based sample index within the collection run."""


class LatencyCollector:
    """Collect latency samples for a callable."""

    __slots__ = ("_clock", "_warmup")

    def __init__(self, warmup: int = 100) -> None:
        """Create a collector.

        Args:
            warmup: Number of un-timed invocation to perform before sampling.
        """
        if warmup < 0:
            raise ValueError(f"warmup must be >= 0, got {warmup}")
        self._warmup = warmup
        self._clock = time.perf_counter_ns

    @property
    def warmup(self) -> int:
        """Number of warm-up iterations."""
        return self._warmup

    def sample(
        self,
        func: Callable[..., Any],
        *args: Any,
        n: int = 1_000,
        **kwargs: Any,
    ) -> list[Sample]:
        """Measure ``func`` latency over ``n`` timed iterations.

        Args:
            func: Callable to measure.
            *args: Positional arguments forwarded to ``func``.
            n: Number of timed samples to collect. Must be >= 1.
            **kwargs: Keyword arguments forwarded to ``func``.

        Returns:
            A list of :class:`Sample`, one per iteration, in collection order.

        Raises:
            ValueError: ``n`` is less than 1.
        """
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n}")

        name = getattr(func, "__qualname__", getattr(func, "__name__", str(func)))

        # Warm up: run the callable without timing so that caches, frequency
        # scaling and interpreter effects are amortized before measurement.
        for _ in range(self._warmup):
            func(*args, **kwargs)

        samples: list[Sample] = []
        for i in range(n):
            start = self._clock()
            func(*args, **kwargs)
            end = self._clock()
            samples.append(Sample(func_name=name, latency_ns=end - start, iteration=i))

        return samples
