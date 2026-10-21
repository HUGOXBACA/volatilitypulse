// ─────────────────────────────────────────────────────────────────────────────
// Statistical analysis of latency samples using the C++ standard library.
//
// Mirrors the Python SciPy-based analysis in volpulse_core.latency.analysis:
//
//   * descriptive statistics (count, min, max, mean, variance, skewness,
//     kurtosis) computed manually from the sample,
//   * percentiles (p50, p90, p95, p99, p99.9) via sorted-index quantiles,
//   * distribution fitting (Normal, LogNormal, Exponential) by maximum
//     likelihood, ranked by Kolmogorov-Smirnov distance. CDFs use std::erf
//     (C++11), so there is no external dependency beyond the toolchain,
//   * outlier detection via the Tukey IQR fence and modified z-score,
//   * bootstrap confidence intervals for the mean and median (manual
//     resampling with a fixed seed for reproducibility).
//
// All latencies are reported in nanoseconds.
// ─────────────────────────────────────────────────────────────────────────────
#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <numeric>
#include <random>
#include <string>
#include <utility>
#include <vector>

#include "volpulse/latency/collector.h"

namespace volpulse::latency {

/// Result of fitting one candidate distribution.
struct DistributionFit {
  std::string name;            // "normal", "lognormal", "exponential"
  std::vector<double> params;  // maximum-likelihood parameters
  double ks_statistic = 0.0;   // Kolmogorov-Smirnov distance to ECDF
  double ks_pvalue = 0.0;      // approximate K-S p-value
};

/// Outlier detection summary.
struct OutlierReport {
  std::int64_t iqr_count = 0;         // samples outside the Tukey fence
  double iqr_fence_low = 0.0;         // Q1 - 1.5 * IQR
  double iqr_fence_high = 0.0;        // Q3 + 1.5 * IQR
  std::int64_t modified_z_count = 0;  // samples with |mod z| > 3.5
  double modified_z_threshold = 3.5;
};

/// Complete statistical analysis of one latency sample set.
struct LatencyReport {
  std::string func_name;
  std::size_t sample_count = 0;
  std::size_t warmup_count = 0;

  // Descriptive statistics.
  double min_ns = 0.0;
  double max_ns = 0.0;
  double mean_ns = 0.0;
  double variance_ns = 0.0;
  double skewness = 0.0;
  double kurtosis = 0.0;

  // Percentiles (nanoseconds).
  double p50_ns = 0.0;
  double p90_ns = 0.0;
  double p95_ns = 0.0;
  double p99_ns = 0.0;
  double p99_9_ns = 0.0;

  // Distribution fitting.
  std::vector<DistributionFit> all_fits;
  DistributionFit best_fit{};  // empty name means "no fit"

  // Outliers.
  OutlierReport outliers{};

  // Bootstrap 95% confidence intervals.
  double mean_ci_low_ns = 0.0;
  double mean_ci_high_ns = 0.0;
  double median_ci_low_ns = 0.0;
  double median_ci_high_ns = 0.0;

  // Convenience accessors.
  [[nodiscard]] double mean_us() const noexcept {
    return mean_ns / 1'000.0;
  }
  [[nodiscard]] double p99_us() const noexcept {
    return p99_ns / 1'000.0;
  }
  [[nodiscard]] double p99_9_us() const noexcept {
    return p99_9_ns / 1'000.0;
  }
  [[nodiscard]] double max_us() const noexcept {
    return max_ns / 1'000.0;
  }
  [[nodiscard]] bool has_fit() const noexcept {
    return !best_fit.name.empty();
  }
};

namespace detail {

/// Standard normal CDF via std::erf.
[[nodiscard]] inline double normal_cdf(double x) {
  return 0.5 * (1.0 + std::erf(x / std::sqrt(2.0)));
}

/// Log-normal CDF: Phi((ln(x) - mu) / sigma).
[[nodiscard]] inline double lognormal_cdf(double x, double mu, double sigma) {
  if (x <= 0.0) return 0.0;
  return normal_cdf((std::log(x) - mu) / sigma);
}

/// Exponential CDF: 1 - exp(-lambda * x).
[[nodiscard]] inline double exponential_cdf(double x, double lambda) {
  if (x < 0.0) return 0.0;
  return 1.0 - std::exp(-lambda * x);
}

/// Kolmogorov-Smirnov distance between the empirical CDF of sorted data and
/// a theoretical CDF. p-value uses the asymptotic Kolmogorov approximation.
template <typename CdfFn>
[[nodiscard]] DistributionFit fit_one(std::string name, CdfFn cdf,
                                      const std::vector<double>& sorted,
                                      std::vector<double> params = {}) {
  DistributionFit fit;
  fit.name = std::move(name);
  fit.params = std::move(params);
  const std::size_t n = sorted.size();

  double ks = 0.0;
  for (std::size_t i = 0; i < n; ++i) {
    const double empirical = static_cast<double>(i + 1) / static_cast<double>(n);
    const double theoretical = cdf(sorted[i]);
    const double diff = std::abs(empirical - theoretical);
    if (diff > ks) {
      ks = diff;
    }
  }
  fit.ks_statistic = ks;
  // Asymptotic Kolmogorov approximation: P(D_n > ks) ≈ exp(-2 n ks^2).
  const double lambda = ks * std::sqrt(static_cast<double>(n));
  fit.ks_pvalue = std::exp(-2.0 * lambda * lambda);
  if (fit.ks_pvalue > 1.0) {
    fit.ks_pvalue = 1.0;
  }
  return fit;
}

/// Draw `n_resamples` bootstrap resamples with replacement and return the
/// (low, high) percentile confidence interval for `statistic`.
[[nodiscard]] std::pair<double, double> bootstrap_ci(
  const std::vector<double>& data, double (*statistic)(const std::vector<double>&),
  std::size_t n_resamples, double confidence, std::uint32_t seed) {
  std::mt19937_64 rng(seed);
  std::uniform_int_distribution<std::size_t> index(0, data.size() - 1);

  std::vector<double> stats;
  stats.reserve(n_resamples);
  for (std::size_t r = 0; r < n_resamples; ++r) {
    std::vector<double> sample;
    sample.reserve(data.size());
    for (std::size_t i = 0; i < data.size(); ++i) {
      sample.push_back(data[index(rng)]);
    }
    stats.push_back(statistic(sample));
  }

  std::sort(stats.begin(), stats.end());
  const double tail = (1.0 - confidence) / 2.0;
  const std::size_t lo = static_cast<std::size_t>(tail * static_cast<double>(n_resamples));
  const std::size_t hi =
    static_cast<std::size_t>((1.0 - tail) * static_cast<double>(n_resamples)) - 1;
  return {stats[lo], stats[hi]};
}

}  // namespace detail

/// Analyze a collection of latency samples.
[[nodiscard]] inline LatencyReport analyze(const std::vector<Sample>& samples,
                                           std::size_t warmup = 0, bool fit_distributions = true,
                                           bool bootstrap = true,
                                           std::size_t n_bootstrap = 10'000) {
  LatencyReport report;
  report.sample_count = samples.size();
  report.warmup_count = warmup;
  if (samples.empty()) {
    return report;
  }
  report.func_name = samples.front().func_name;

  std::vector<double> data;
  data.reserve(samples.size());
  for (const auto& s : samples) {
    data.push_back(static_cast<double>(s.latency_ns));
  }
  std::vector<double> sorted = data;
  std::sort(sorted.begin(), sorted.end());

  const std::size_t n = data.size();

  // ── Descriptive statistics ─────────────────────────────────────────
  double sum = 0.0;
  double min_v = data[0];
  double max_v = data[0];
  for (double v : data) {
    sum += v;
    if (v < min_v) min_v = v;
    if (v > max_v) max_v = v;
  }
  report.min_ns = min_v;
  report.max_ns = max_v;
  report.mean_ns = sum / n;

  double var_sum = 0.0;
  double skew_sum = 0.0;
  double kurt_sum = 0.0;
  const double mean = report.mean_ns;
  for (double v : data) {
    const double d = v - mean;
    var_sum += d * d;
    skew_sum += d * d * d;
    kurt_sum += d * d * d * d;
  }
  const double variance = var_sum / n;
  report.variance_ns = variance;
  const double std_dev = std::sqrt(variance);
  if (std_dev > 0.0) {
    report.skewness = (skew_sum / n) / (std_dev * std_dev * std_dev);
    report.kurtosis = (kurt_sum / n) / (variance * variance) - 3.0;
  }

  // ── Percentiles (sorted-index, linear interpolation) ───────────────
  auto percentile = [&sorted](double p) {
    if (sorted.empty()) return 0.0;
    const double idx = p * (sorted.size() - 1);
    const std::size_t lo = static_cast<std::size_t>(idx);
    const std::size_t hi = std::min(lo + 1, sorted.size() - 1);
    const double frac = idx - lo;
    return sorted[lo] + frac * (sorted[hi] - sorted[lo]);
  };
  report.p50_ns = percentile(0.50);
  report.p90_ns = percentile(0.90);
  report.p95_ns = percentile(0.95);
  report.p99_ns = percentile(0.99);
  report.p99_9_ns = percentile(0.999);

  // ── Distribution fitting (maximum likelihood, ranked by K-S) ────────
  if (fit_distributions && data.size() > 10) {
    std::vector<DistributionFit> fits;

    // Normal: mu = mean, sigma = std (MLE uses n denominator).
    const double sigma = std::sqrt(variance * (n - 1) / n);
    if (sigma > 0.0) {
      fits.push_back(detail::fit_one(
        "normal", [mean, sigma](double x) { return detail::normal_cdf((x - mean) / sigma); },
        sorted, {mean, sigma}));
    }

    // LogNormal: mu = mean(log), sigma = std(log).
    double log_mean = 0.0;
    for (double v : data) log_mean += std::log(v);
    log_mean /= n;
    double log_var = 0.0;
    for (double v : data) {
      const double d = std::log(v) - log_mean;
      log_var += d * d;
    }
    log_var /= n;
    const double log_sigma = std::sqrt(log_var);
    if (log_sigma > 0.0) {
      fits.push_back(detail::fit_one(
        "lognormal",
        [log_mean, log_sigma](double x) { return detail::lognormal_cdf(x, log_mean, log_sigma); },
        sorted, {log_mean, log_sigma}));
    }

    // Exponential: lambda = 1 / mean.
    if (report.mean_ns > 0.0) {
      fits.push_back(detail::fit_one(
        "exponential", [mean](double x) { return detail::exponential_cdf(x, 1.0 / mean); }, sorted,
        {1.0 / mean}));
    }

    std::sort(fits.begin(), fits.end(), [](const DistributionFit& a, const DistributionFit& b) {
      return a.ks_statistic < b.ks_statistic;
    });
    report.all_fits = std::move(fits);
    if (!report.all_fits.empty()) {
      report.best_fit = report.all_fits.front();
    }
  }

  // ── Outlier detection ───────────────────────────────────────────────
  const double q1 = percentile(0.25);
  const double q3 = percentile(0.75);
  const double iqr = q3 - q1;
  report.outliers.iqr_fence_low = q1 - 1.5 * iqr;
  report.outliers.iqr_fence_high = q3 + 1.5 * iqr;
  for (double v : data) {
    if (v < report.outliers.iqr_fence_low || v > report.outliers.iqr_fence_high) {
      ++report.outliers.iqr_count;
    }
  }

  const double median = percentile(0.5);
  double mad = 0.0;
  for (double v : data) {
    mad += std::abs(v - median);
  }
  mad /= n;
  if (mad > 0.0) {
    for (double v : data) {
      const double mz = 0.6745 * (v - median) / mad;
      if (std::abs(mz) > report.outliers.modified_z_threshold) {
        ++report.outliers.modified_z_count;
      }
    }
  }

  // ── Bootstrap confidence intervals ─────────────────────────────────
  auto mean_stat = [](const std::vector<double>& d) {
    double s = 0.0;
    for (double v : d) s += v;
    return s / d.size();
  };
  auto median_stat = [](const std::vector<double>& d) {
    std::vector<double> s = d;
    std::sort(s.begin(), s.end());
    return s[s.size() / 2];
  };

  if (bootstrap && data.size() > 10) {
    auto [lo, hi] = detail::bootstrap_ci(data, mean_stat, n_bootstrap, 0.95, 42);
    report.mean_ci_low_ns = lo;
    report.mean_ci_high_ns = hi;
    std::tie(report.median_ci_low_ns, report.median_ci_high_ns) =
      detail::bootstrap_ci(data, median_stat, n_bootstrap, 0.95, 43);
  }

  return report;
}

/// Standalone outlier detection for a vector of latencies (ns).
[[nodiscard]] inline OutlierReport detect_outliers(const std::vector<double>& latencies) {
  OutlierReport out;
  if (latencies.empty()) {
    return out;
  }
  std::vector<double> s = latencies;
  std::sort(s.begin(), s.end());
  const std::size_t n = s.size();
  const auto percentile = [&s, n](double p) {
    const double idx = p * (n - 1);
    const std::size_t lo = static_cast<std::size_t>(idx);
    const std::size_t hi = std::min(lo + 1, n - 1);
    const double frac = idx - lo;
    return s[lo] + frac * (s[hi] - s[lo]);
  };
  const double q1 = percentile(0.25);
  const double q3 = percentile(0.75);
  const double iqr = q3 - q1;
  out.iqr_fence_low = q1 - 1.5 * iqr;
  out.iqr_fence_high = q3 + 1.5 * iqr;
  for (double v : s) {
    if (v < out.iqr_fence_low || v > out.iqr_fence_high) {
      ++out.iqr_count;
    }
  }
  const double median = percentile(0.5);
  double mad = 0.0;
  for (double v : s) {
    mad += std::abs(v - median);
  }
  mad /= n;
  if (mad > 0.0) {
    for (double v : s) {
      const double mz = 0.6745 * (v - median) / mad;
      if (std::abs(mz) > out.modified_z_threshold) {
        ++out.modified_z_count;
      }
    }
  }
  return out;
}

}  // namespace volpulse::latency
