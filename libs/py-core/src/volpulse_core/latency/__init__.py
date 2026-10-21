# ─────────────────────────────────────────────────────────────────────────────
# Latency measurement utilities.
#
# High-resolution function-latency sampling using ``time.perf_counter_ns``,
# with statistical analysis powered by SciPy and structured JSON / text
# report output.
#
#   from volpulse_core.latency import LatencyCollector, analyze, render_report
#   collector = LatencyCollector()
#   samples = collector.sample(my_function, *args, n=10_000)
#   report = analyze(samples, name="my_function")
#   print(render_report(report))
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from .analysis import LatencyReport, analyze, detect_outliers
from .collector import LatencyCollector, Sample
from .report import render_report, write_report

__all__ = [
    "LatencyCollector",
    "LatencyReport",
    "Sample",
    "analyze",
    "detect_outliers",
    "render_report",
    "write_report",
]
