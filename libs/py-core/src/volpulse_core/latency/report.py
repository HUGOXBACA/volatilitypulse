# ─────────────────────────────────────────────────────────────────────────────
# Report rendering for latency analysis.
#
# Produces a human-readable text report and a JSON-serializable dictionary
# from a :class:`~volpulse_core.latency.analysis.LatencyReport`. Reports can
# be written to ``var/artifacts/latency_<func>_<timestamp>.json|.txt``.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

from .analysis import LatencyReport

__all__ = ["render_report", "write_report"]


def _fmt_ns(value: float) -> str:
    """Format a nanosecond value with an appropriate unit suffix."""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.4f} s"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.4f} ms"
    if value >= 1_000:
        return f"{value / 1_000:.4f} µs"
    return f"{value:.2f} ns"


def render_report(report: LatencyReport) -> str:
    """Render a human-readable latency report."""
    lines: list[str] = []
    lines.append("═" * 72)
    lines.append(f"Latency report: {report.func_name}")
    lines.append(f"Generated: {datetime.now(UTC).isoformat()}Z")
    lines.append("═" * 72)
    lines.append("")
    lines.append("Sample summary")
    lines.append("-" * 72)
    lines.append(f"  samples        : {report.sample_count:,}")
    lines.append(f"  warm-up        : {report.warmup_count}")
    lines.append(f"  unit           : {report.unit}")
    lines.append("")
    lines.append("Descriptive statistics (scipy.stats.describe)")
    lines.append("-" * 72)
    lines.append(f"  min            : {_fmt_ns(report.min_ns)}")
    lines.append(f"  max            : {_fmt_ns(report.max_ns)}")
    lines.append(
        f"  mean           : {_fmt_ns(report.mean_ns)}  "
        f"(±{_fmt_ns(math.sqrt(report.variance_ns)) if report.variance_ns >= 0 else 'n/a'})"
    )
    lines.append(f"  variance       : {report.variance_ns:.6f} ns²")
    lines.append(f"  skewness       : {report.skewness:+.4f}")
    lines.append(f"  kurtosis       : {report.kurtosis:+.4f}")
    lines.append("")
    lines.append("Percentiles")
    lines.append("-" * 72)
    lines.append(f"  p50            : {_fmt_ns(report.p50_ns)}  ({report.p50_ns / 1000:.4f} µs)")
    lines.append(f"  p90            : {_fmt_ns(report.p90_ns)}  ({report.p90_ns / 1000:.4f} µs)")
    lines.append(f"  p95            : {_fmt_ns(report.p95_ns)}  ({report.p95_ns / 1000:.4f} µs)")
    lines.append(f"  p99            : {_fmt_ns(report.p99_ns)}  ({report.p99_ns / 1000:.4f} µs)")
    lines.append(
        f"  p99.9          : {_fmt_ns(report.p99_9_ns)}  ({report.p99_9_ns / 1000:.4f} µs)"
    )
    lines.append("")
    lines.append("Distribution fitting (maximum likelihood, ranked by K-S distance)")
    lines.append("-" * 72)
    if report.best_fit is not None:
        lines.append(f"  best fit       : {report.best_fit.name}")
        lines.append(f"  K-S statistic  : {report.best_fit.ks_statistic:.6f}")
        lines.append(f"  K-S p-value    : {report.best_fit.ks_pvalue:.6f}")
        lines.append(f"  params         : {list(report.best_fit.params)}")
        if report.all_fits:
            lines.append("  all fits:")
            for fit in report.all_fits:
                lines.append(
                    f"    - {fit.name:14s} ks={fit.ks_statistic:.6f} p={fit.ks_pvalue:.6f}"
                )
    else:
        lines.append("  (insufficient samples for fitting)")
    lines.append("")
    lines.append("Outlier detection")
    lines.append("-" * 72)
    if report.outliers is not None:
        lines.append(
            f"  IQR fence      : [{_fmt_ns(report.outliers.iqr_fence_low)}, "
            f"{_fmt_ns(report.outliers.iqr_fence_high)}]"
        )
        lines.append(f"  IQR outliers   : {report.outliers.iqr_count}")
        lines.append(
            f"  mod-z outliers : {report.outliers.modified_z_count} "
            f"(threshold {report.outliers.modified_z_threshold})"
        )
    lines.append("")
    lines.append("Bootstrap 95% confidence intervals")
    lines.append("-" * 72)
    if not math.isnan(report.mean_ci_low_ns):
        lines.append(
            f"  mean           : [{_fmt_ns(report.mean_ci_low_ns)}, "
            f"{_fmt_ns(report.mean_ci_high_ns)}]"
        )
        lines.append(
            f"  median         : [{_fmt_ns(report.median_ci_low_ns)}, "
            f"{_fmt_ns(report.median_ci_high_ns)}]"
        )
    else:
        lines.append("  (insufficient samples for bootstrap)")
    lines.append("")
    lines.append("═" * 72)
    return "\n".join(lines)


def write_report(
    report: LatencyReport, directory: Path | str = "var/artifacts"
) -> tuple[Path, Path]:
    """Write the report as JSON and text files.

    Args:
        report: The latency report to persist.
        directory: Output directory (created if missing).

    Returns:
        A tuple of ``(json_path, text_path)``.
    """
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in report.func_name)

    json_path = out_dir / f"latency_{safe_name}_{stamp}.json"
    text_path = out_dir / f"latency_{safe_name}_{stamp}.txt"

    json_path.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    text_path.write_text(render_report(report) + "\n", encoding="utf-8")

    return json_path, text_path
