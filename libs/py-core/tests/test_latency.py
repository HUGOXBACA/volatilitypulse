"""Tests for the SciPy-based latency measurement and analysis module."""

from __future__ import annotations

import pytest
from volpulse_core.latency import LatencyCollector, Sample, analyze, detect_outliers

__all__ = [
    "test_analyze_constant_data",
    "test_analyze_sane_statistics",
    "test_collector_produces_samples",
    "test_detect_outliers",
]


def test_collector_produces_samples() -> None:
    """The collector yields one sample per iteration with non-negative latency."""
    state = [0]

    def sink() -> None:
        state[0] += 1

    collector = LatencyCollector(warmup=10)
    samples = collector.sample(sink, n=100)

    assert len(samples) == 100
    assert state[0] == 110  # 10 warm-up + 100 timed
    for sample in samples:
        assert sample.func_name.endswith("sink")
        assert sample.latency_ns >= 0
        assert sample.iteration < 100
    assert collector.warmup == 10


def test_analyze_sane_statistics() -> None:
    """Descriptive statistics and percentiles must be ordered sensibly."""
    samples = [Sample("ramp", 100 + i, i) for i in range(1000)]

    report = analyze(samples, warmup=0, fit_distributions=True, bootstrap=True, n_bootstrap=1000)

    assert report.sample_count == 1000
    assert report.func_name == "ramp"
    assert report.min_ns <= report.mean_ns <= report.max_ns
    assert report.p50_ns <= report.p90_ns <= report.p95_ns <= report.p99_ns <= report.p99_9_ns
    assert report.variance_ns >= 0.0
    assert report.best_fit is not None
    assert report.best_fit.name in {"norm", "lognorm", "expon", "weibull_min", "gamma"}
    assert 0.0 <= report.best_fit.ks_pvalue <= 1.0
    assert report.outliers.iqr_count >= 0


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_analyze_constant_data() -> None:
    """Constant data has zero variance and min == max == mean."""
    samples = [Sample("const", 500, i) for i in range(100)]

    report = analyze(samples, warmup=0, fit_distributions=True, bootstrap=True, n_bootstrap=1000)

    assert report.min_ns == 500.0
    assert report.max_ns == 500.0
    assert report.mean_ns == 500.0
    assert report.variance_ns == 0.0


def test_detect_outliers() -> None:
    """An obvious outlier is detected by both IQR and modified z-score."""
    data = [100.0, 101.0, 102.0, 103.0, 104.0, 1000.0]
    out = detect_outliers(data)

    assert out["iqr_count"] >= 1
    assert out["modified_z_count"] >= 1
