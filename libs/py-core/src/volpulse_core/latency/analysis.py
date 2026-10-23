# ─────────────────────────────────────────────────────────────────────────────
# Statistical analysis of latency samples using SciPy.
#
# For each sample set the analysis computes:
#
#   * Descriptive statistics (count, min, max, mean, median, variance, skew,
#     kurtosis) via :func:`scipy.stats.describe`.
#   * Percentiles (p50, p90, p95, p99, p99.9) via NumPy / SciPy.
#   * Distribution fitting: Normal, LogNormal, Exponential, Gamma and
#     Weibull are fit by maximum likelihood and ranked by Kolmogorov-Smirnov
#     distance against the empirical CDF.
#   * Goodness-of-fit for the best distribution via the K-S test.
#   * Outlier detection via the IQR fence (Tukey) and modified z-score.
#   * Bootstrap confidence intervals for the mean and median via
#     :func:`scipy.stats.bootstrap`.
#
# All latencies are reported in nanoseconds and (where convenient) also in
# microseconds and milliseconds so the report is readable at any scale.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats

__all__ = [
    "DistributionFit",
    "LatencyReport",
    "OutlierReport",
    "analyze",
    "detect_outliers",
]

_DISTRIBUTIONS = [
    ("norm", stats.norm),
    ("lognorm", stats.lognorm),
    ("expon", stats.expon),
    ("gamma", stats.gamma),
    ("weibull_min", stats.weibull_min),
]


@dataclass(frozen=True, slots=True)
class DistributionFit:
    """Result of fitting one candidate distribution."""

    name: str
    """Distribution name, e.g. ``"lognorm"``."""
    params: tuple[float, ...]
    """Maximum-likelihood parameters."""
    ks_statistic: float
    """Kolmogorov-Smirnov distance to the empirical CDF."""
    ks_pvalue: float
    """K-S test p-value; larger means the fit is more plausible."""


@dataclass(frozen=True, slots=True)
class OutlierReport:
    """Outlier detection summary."""

    iqr_count: int
    """Number of samples outside the Tukey IQR fence."""
    iqr_fence_low: float
    """Lower Tukey fence (Q1 - 1.5 * IQR)."""
    iqr_fence_high: float
    """Upper Tukey fence (Q3 + 1.5 * IQR)."""
    modified_z_count: int
    """Number of samples with |modified z-score| > 3.5."""
    modified_z_threshold: float
    """Modified z-score threshold (3.5)."""


@dataclass(frozen=True, slots=True)
class LatencyReport:
    """Complete statistical analysis of one latency sample set."""

    func_name: str
    sample_count: int
    warmup_count: int
    unit: str = "ns"

    # Raw descriptive statistics (scipy.stats.describe).
    min_ns: float = 0.0
    max_ns: float = 0.0
    mean_ns: float = 0.0
    variance_ns: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0

    # Percentiles.
    p50_ns: float = 0.0
    p90_ns: float = 0.0
    p95_ns: float = 0.0
    p99_ns: float = 0.0
    p99_9_ns: float = 0.0

    # Distribution fitting.
    best_fit: DistributionFit | None = None
    all_fits: list[DistributionFit] = field(default_factory=list)

    # Outliers.
    outliers: OutlierReport | None = None

    # Bootstrap confidence intervals (95%).
    mean_ci_low_ns: float = 0.0
    mean_ci_high_ns: float = 0.0
    median_ci_low_ns: float = 0.0
    median_ci_high_ns: float = 0.0

    # Derived convenience units.
    @property
    def mean_us(self) -> float:
        return self.mean_ns / 1_000.0

    @property
    def p99_us(self) -> float:
        return self.p99_ns / 1_000.0

    @property
    def p99_9_us(self) -> float:
        return self.p99_9_ns / 1_000.0

    @property
    def max_us(self) -> float:
        return self.max_ns / 1_000.0

    def as_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "func_name": self.func_name,
            "unit": self.unit,
            "sample_count": self.sample_count,
            "warmup_count": self.warmup_count,
            "descriptive": {
                "min_ns": self.min_ns,
                "max_ns": self.max_ns,
                "mean_ns": self.mean_ns,
                "variance_ns": self.variance_ns,
                "std_dev_ns": math.sqrt(self.variance_ns)
                if self.variance_ns >= 0
                else float("nan"),
                "skewness": self.skewness,
                "kurtosis": self.kurtosis,
            },
            "percentiles_ns": {
                "p50": self.p50_ns,
                "p90": self.p90_ns,
                "p95": self.p95_ns,
                "p99": self.p99_ns,
                "p99_9": self.p99_9_ns,
            },
            "percentiles_us": {
                "p50": self.p50_ns / 1_000.0,
                "p90": self.p90_ns / 1_000.0,
                "p95": self.p95_ns / 1_000.0,
                "p99": self.p99_ns / 1_000.0,
                "p99_9": self.p99_9_ns / 1_000.0,
            },
            "distribution_fit": (
                {
                    "name": self.best_fit.name,
                    "ks_statistic": float(self.best_fit.ks_statistic),
                    "ks_pvalue": float(self.best_fit.ks_pvalue),
                    "params": [float(p) for p in self.best_fit.params],
                }
                if self.best_fit is not None
                else None
            ),
            "all_fits": [
                {
                    "name": fit.name,
                    "ks_statistic": float(fit.ks_statistic),
                    "ks_pvalue": float(fit.ks_pvalue),
                    "params": [float(p) for p in fit.params],
                }
                for fit in self.all_fits
            ],
            "outliers": (
                {
                    "iqr_count": self.outliers.iqr_count,
                    "iqr_fence_low_ns": self.outliers.iqr_fence_low,
                    "iqr_fence_high_ns": self.outliers.iqr_fence_high,
                    "modified_z_count": self.outliers.modified_z_count,
                    "modified_z_threshold": self.outliers.modified_z_threshold,
                }
                if self.outliers is not None
                else None
            ),
            "confidence_intervals_95_ns": {
                "mean": [self.mean_ci_low_ns, self.mean_ci_high_ns],
                "median": [self.median_ci_low_ns, self.median_ci_high_ns],
            },
        }


def _fit_distributions(data: np.ndarray) -> list[DistributionFit]:
    """Fit candidate distributions and rank by K-S distance."""
    fits: list[DistributionFit] = []
    sorted_data = np.sort(data)
    ecdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)

    for name, dist in _DISTRIBUTIONS:
        try:
            params = dist.fit(data)
        except (ValueError, RuntimeError):
            # Some distributions fail to converge on degenerate data.
            continue

        # Theoretical CDF at the observed points.
        try:
            theoretical_cdf = dist.cdf(sorted_data, *params)
        except (ValueError, RuntimeError):
            continue

        ks_statistic = float(np.max(np.abs(ecdf - theoretical_cdf)))
        try:
            ks_pvalue = float(stats.kstest(data, dist.cdf, args=params).pvalue)
        except (ValueError, RuntimeError):
            ks_pvalue = float("nan")

        fits.append(
            DistributionFit(
                name=name,
                params=params,
                ks_statistic=ks_statistic,
                ks_pvalue=ks_pvalue,
            )
        )

    fits.sort(key=lambda f: f.ks_statistic)
    return fits


def _bootstrap_ci(
    data: np.ndarray,
    statistic: str,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
) -> tuple[float, float]:
    """Bootstrap confidence interval for the mean or median."""
    if statistic == "mean":
        stat_func: Callable[[np.ndarray], float] = np.mean
    elif statistic == "median":
        stat_func = np.median
    else:  # pragma: no cover - guarded by caller
        raise ValueError(f"unknown statistic {statistic!r}")

    result = stats.bootstrap(
        (data,),
        stat_func,
        n_resamples=n_resamples,
        confidence_level=confidence,
        method="basic",
        random_state=42,
    )
    return float(result.confidence_interval.low), float(result.confidence_interval.high)


def analyze(
    samples: Sequence[Any],
    *,
    warmup: int = 0,
    fit_distributions: bool = True,
    bootstrap: bool = True,
    n_bootstrap: int = 10_000,
) -> LatencyReport:
    """Analyze a collection of latency samples.

    Args:
        samples: Sequence of :class:`~volpulse_core.latency.collector.Sample`
            objects (or any objects with a ``latency_ns`` attribute).
        warmup: Number of warm-up iterations that preceded sampling (for
            reporting only; the samples themselves should already exclude
            warm-up).
        fit_distributions: When true, fit candidate distributions and rank by
            K-S distance.
        bootstrap: When true, compute bootstrap confidence intervals for the
            mean and median.
        n_bootstrap: Number of bootstrap resamples.

    Returns:
        A :class:`LatencyReport` with descriptive statistics, percentiles,
        distribution fits, outlier detection and confidence intervals.
    """
    latencies = np.array([float(s.latency_ns) for s in samples], dtype=np.float64)
    if latencies.size == 0:
        raise ValueError("samples must not be empty")

    func_name = getattr(samples[0], "func_name", "unknown")

    # ── Descriptive statistics via scipy.stats.describe ──────────────────
    desc = stats.describe(latencies)
    min_ns = float(desc.minmax[0])
    max_ns = float(desc.minmax[1])
    mean_ns = float(desc.mean)
    variance_ns = float(desc.variance)
    skewness = float(desc.skewness)
    kurtosis = float(desc.kurtosis)

    # ── Percentiles ──────────────────────────────────────────────────────
    percentiles = np.percentile(latencies, [50, 90, 95, 99, 99.9])
    p50_ns, p90_ns, p95_ns, p99_ns, p99_9_ns = (float(v) for v in percentiles)

    # ── Distribution fitting ─────────────────────────────────────────────
    all_fits: list[DistributionFit] = []
    best_fit: DistributionFit | None = None
    if fit_distributions and latencies.size > 10:
        all_fits = _fit_distributions(latencies)
        if all_fits:
            best_fit = all_fits[0]

    # ── Outlier detection ────────────────────────────────────────────────
    q1 = float(np.percentile(latencies, 25))
    q3 = float(np.percentile(latencies, 75))
    iqr = q3 - q1
    fence_low = q1 - 1.5 * iqr
    fence_high = q3 + 1.5 * iqr
    iqr_count = int(np.count_nonzero((latencies < fence_low) | (latencies > fence_high)))

    median = float(np.median(latencies))
    mad = float(np.median(np.abs(latencies - median))) or 1.0  # avoid div by zero
    modified_z = 0.6745 * (latencies - median) / mad
    mz_count = int(np.count_nonzero(np.abs(modified_z) > 3.5))

    outliers = OutlierReport(
        iqr_count=iqr_count,
        iqr_fence_low=fence_low,
        iqr_fence_high=fence_high,
        modified_z_count=mz_count,
        modified_z_threshold=3.5,
    )

    # ── Bootstrap confidence intervals ───────────────────────────────────
    mean_ci_low = mean_ci_high = float("nan")
    median_ci_low = median_ci_high = float("nan")
    if bootstrap and latencies.size > 10:
        mean_ci_low, mean_ci_high = _bootstrap_ci(latencies, "mean", n_resamples=n_bootstrap)
        median_ci_low, median_ci_high = _bootstrap_ci(latencies, "median", n_resamples=n_bootstrap)

    return LatencyReport(
        func_name=func_name,
        sample_count=int(latencies.size),
        warmup_count=int(warmup),
        min_ns=min_ns,
        max_ns=max_ns,
        mean_ns=mean_ns,
        variance_ns=variance_ns,
        skewness=skewness,
        kurtosis=kurtosis,
        p50_ns=p50_ns,
        p90_ns=p90_ns,
        p95_ns=p95_ns,
        p99_ns=p99_ns,
        p99_9_ns=p99_9_ns,
        best_fit=best_fit,
        all_fits=all_fits,
        outliers=outliers,
        mean_ci_low_ns=mean_ci_low,
        mean_ci_high_ns=mean_ci_high,
        median_ci_low_ns=median_ci_low,
        median_ci_high_ns=median_ci_high,
    )


def detect_outliers(latencies: Sequence[float]) -> dict[str, Any]:
    """Standalone outlier detection for a sequence of latencies (ns).

    Returns a dictionary with IQR fence counts and modified z-score counts.
    """
    arr = np.array(latencies, dtype=np.float64)
    if arr.size == 0:
        return {"iqr_count": 0, "modified_z_count": 0}

    q1 = float(np.percentile(arr, 25))
    q3 = float(np.percentile(arr, 75))
    iqr = q3 - q1
    fence_low = q1 - 1.5 * iqr
    fence_high = q3 + 1.5 * iqr
    iqr_count = int(np.count_nonzero((arr < fence_low) | (arr > fence_high)))

    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median))) or 1.0
    modified_z = 0.6745 * (arr - median) / mad
    mz_count = int(np.count_nonzero(np.abs(modified_z) > 3.5))

    return {
        "iqr_count": iqr_count,
        "iqr_fence_low_ns": fence_low,
        "iqr_fence_high_ns": fence_high,
        "modified_z_count": mz_count,
        "modified_z_threshold": 3.5,
        "outlier_indices_iqr": np.nonzero((arr < fence_low) | (arr > fence_high))[0].tolist(),
        "outlier_indices_modified_z": np.nonzero(np.abs(modified_z) > 3.5)[0].tolist(),
    }
