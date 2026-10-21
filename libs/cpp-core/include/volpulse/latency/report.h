// ─────────────────────────────────────────────────────────────────────────────
// Report rendering for C++ latency analysis.
//
// Produces a human-readable text report and a JSON file (hand-written, no
// dependency) from a LatencyReport, mirroring the Python report module.
// ─────────────────────────────────────────────────────────────────────────────
#pragma once

#include <sys/stat.h>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <fstream>
#include <string>
#include <utility>
#include <vector>

#include "volpulse/latency/analysis.h"

namespace volpulse::latency {

namespace detail {

[[nodiscard]] inline std::string fmt_ns(double value) {
  char buf[64];
  if (value >= 1'000'000'000.0) {
    std::snprintf(buf, sizeof(buf), "%.4f s", value / 1'000'000'000.0);
  } else if (value >= 1'000'000.0) {
    std::snprintf(buf, sizeof(buf), "%.4f ms", value / 1'000'000.0);
  } else if (value >= 1'000.0) {
    std::snprintf(buf, sizeof(buf), "%.4f us", value / 1'000.0);
  } else {
    std::snprintf(buf, sizeof(buf), "%.2f ns", value);
  }
  return buf;
}

[[nodiscard]] inline std::string utc_timestamp() {
  const auto now = std::chrono::system_clock::now();
  const std::time_t t = std::chrono::system_clock::to_time_t(now);
  std::tm tm{};
#if defined(_WIN32)
  gmtime_s(&tm, &t);
#else
  gmtime_r(&t, &tm);
#endif
  char buf[32];
  std::strftime(buf, sizeof(buf), "%Y%m%dT%H%M%SZ", &tm);
  return buf;
}

[[nodiscard]] inline std::string safe_name(std::string_view name) {
  std::string out;
  out.reserve(name.size());
  for (char c : name) {
    out.push_back((std::isalnum(static_cast<unsigned char>(c)) || c == '-' || c == '_') ? c : '_');
  }
  return out;
}

}  // namespace detail

/// Render a human-readable latency report.
[[nodiscard]] inline std::string render_report(const LatencyReport& report) {
  std::string out;
  out.reserve(2048);

  out += "======================================================================\n";
  out += "Latency report: " + report.func_name + "\n";
  out += "Generated: " + detail::utc_timestamp() + "\n";
  out += "======================================================================\n\n";

  out += "Sample summary\n";
  out += "----------------------------------------------------------------------\n";
  out += "  samples   : " + std::to_string(report.sample_count) + "\n";
  out += "  warm-up   : " + std::to_string(report.warmup_count) + "\n\n";

  out += "Descriptive statistics (Boost.Accumulators)\n";
  out += "----------------------------------------------------------------------\n";
  out += "  min        : " + detail::fmt_ns(report.min_ns) + "\n";
  out += "  max        : " + detail::fmt_ns(report.max_ns) + "\n";
  const double std_dev = report.variance_ns >= 0.0 ? std::sqrt(report.variance_ns) : 0.0;
  out +=
    "  mean       : " + detail::fmt_ns(report.mean_ns) + "  (±" + detail::fmt_ns(std_dev) + ")\n";
  out += "  variance   : " + std::to_string(report.variance_ns) + " ns^2\n";
  out += "  skewness   : " + std::to_string(report.skewness) + "\n";
  out += "  kurtosis   : " + std::to_string(report.kurtosis) + "\n\n";

  out += "Percentiles\n";
  out += "----------------------------------------------------------------------\n";
  out += "  p50        : " + detail::fmt_ns(report.p50_ns) + "  (" +
         std::to_string(report.p50_ns / 1'000.0) + " us)\n";
  out += "  p90        : " + detail::fmt_ns(report.p90_ns) + "  (" +
         std::to_string(report.p90_ns / 1'000.0) + " us)\n";
  out += "  p95        : " + detail::fmt_ns(report.p95_ns) + "  (" +
         std::to_string(report.p95_ns / 1'000.0) + " us)\n";
  out += "  p99        : " + detail::fmt_ns(report.p99_ns) + "  (" +
         std::to_string(report.p99_ns / 1'000.0) + " us)\n";
  out += "  p99.9      : " + detail::fmt_ns(report.p99_9_ns) + "  (" +
         std::to_string(report.p99_9_ns / 1'000.0) + " us)\n\n";

  out += "Distribution fitting (maximum likelihood, ranked by K-S distance)\n";
  out += "----------------------------------------------------------------------\n";
  if (report.has_fit()) {
    out += "  best fit     : " + report.best_fit.name + "\n";
    out += "  K-S stat     : " + std::to_string(report.best_fit.ks_statistic) + "\n";
    out += "  K-S p-val    : " + std::to_string(report.best_fit.ks_pvalue) + "\n";
    out += "  params       : [";
    for (std::size_t i = 0; i < report.best_fit.params.size(); ++i) {
      out += std::to_string(report.best_fit.params[i]);
      if (i + 1 < report.best_fit.params.size()) {
        out += ", ";
      }
    }
    out += "]\n";
    for (const auto& fit : report.all_fits) {
      out += "    - " + fit.name + " ks=" + std::to_string(fit.ks_statistic) +
             " p=" + std::to_string(fit.ks_pvalue) + "\n";
    }
  } else {
    out += "  (insufficient samples for fitting)\n";
  }
  out += "\n";

  out += "Outlier detection\n";
  out += "----------------------------------------------------------------------\n";
  out += "  IQR fence    : [" + detail::fmt_ns(report.outliers.iqr_fence_low) + ", " +
         detail::fmt_ns(report.outliers.iqr_fence_high) + "]\n";
  out += "  IQR outliers : " + std::to_string(report.outliers.iqr_count) + "\n";
  out += "  mod-z outliers: " + std::to_string(report.outliers.modified_z_count) + " (threshold " +
         std::to_string(report.outliers.modified_z_threshold) + ")\n\n";

  out += "Bootstrap 95% confidence intervals\n";
  out += "----------------------------------------------------------------------\n";
  out += "  mean       : [" + detail::fmt_ns(report.mean_ci_low_ns) + ", " +
         detail::fmt_ns(report.mean_ci_high_ns) + "]\n";
  out += "  median     : [" + detail::fmt_ns(report.median_ci_low_ns) + ", " +
         detail::fmt_ns(report.median_ci_high_ns) + "]\n\n";

  out += "======================================================================\n";
  return out;
}

/// Minimal JSON escape for strings.
[[nodiscard]] inline std::string json_escape(std::string_view s) {
  std::string out;
  out.reserve(s.size() + 2);
  for (char c : s) {
    switch (c) {
      case '"':
        out += "\\\"";
        break;
      case '\\':
        out += "\\\\";
        break;
      case '\n':
        out += "\\n";
        break;
      case '\r':
        out += "\\r";
        break;
      case '\t':
        out += "\\t";
        break;
      default:
        out.push_back(c);
        break;
    }
  }
  return out;
}

/// Write the report as JSON and text files.
/// \return Pair of (json_path, text_path).
[[nodiscard]] inline std::pair<std::string, std::string> write_report(
  const LatencyReport& report, std::string directory = "var/artifacts") {
  const std::string stamp = detail::utc_timestamp();
  const std::string name = detail::safe_name(report.func_name);

  // Ensure directory exists (best effort).
#if defined(_WIN32)
  _mkdir(directory.c_str());
#else
  mkdir(directory.c_str(), 0755);
#endif

  const std::string base = directory + "/latency_" + name + "_" + stamp;
  const std::string json_path = base + ".json";
  const std::string text_path = base + ".txt";

  const double std_dev = report.variance_ns >= 0.0 ? std::sqrt(report.variance_ns) : 0.0;

  {
    std::FILE* f = std::fopen(json_path.c_str(), "w");
    if (f) {
      std::fprintf(f, "{\n");
      std::fprintf(f, "  \"func_name\": \"%s\",\n", json_escape(report.func_name).c_str());
      std::fprintf(f, "  \"unit\": \"ns\",\n");
      std::fprintf(f, "  \"sample_count\": %zu,\n", report.sample_count);
      std::fprintf(f, "  \"warmup_count\": %zu,\n", report.warmup_count);
      std::fprintf(f, "  \"descriptive\": {\n");
      std::fprintf(f, "    \"min_ns\": %.6f,\n", report.min_ns);
      std::fprintf(f, "    \"max_ns\": %.6f,\n", report.max_ns);
      std::fprintf(f, "    \"mean_ns\": %.6f,\n", report.mean_ns);
      std::fprintf(f, "    \"variance_ns\": %.6f,\n", report.variance_ns);
      std::fprintf(f, "    \"std_dev_ns\": %.6f,\n", std_dev);
      std::fprintf(f, "    \"skewness\": %.6f,\n", report.skewness);
      std::fprintf(f, "    \"kurtosis\": %.6f\n", report.kurtosis);
      std::fprintf(f, "  },\n");
      std::fprintf(f, "  \"percentiles_ns\": {\n");
      std::fprintf(f, "    \"p50\": %.6f,\n", report.p50_ns);
      std::fprintf(f, "    \"p90\": %.6f,\n", report.p90_ns);
      std::fprintf(f, "    \"p95\": %.6f,\n", report.p95_ns);
      std::fprintf(f, "    \"p99\": %.6f,\n", report.p99_ns);
      std::fprintf(f, "    \"p99_9\": %.6f\n", report.p99_9_ns);
      std::fprintf(f, "  },\n");
      std::fprintf(f, "  \"percentiles_us\": {\n");
      std::fprintf(f, "    \"p50\": %.6f,\n", report.p50_ns / 1'000.0);
      std::fprintf(f, "    \"p90\": %.6f,\n", report.p90_ns / 1'000.0);
      std::fprintf(f, "    \"p95\": %.6f,\n", report.p95_ns / 1'000.0);
      std::fprintf(f, "    \"p99\": %.6f,\n", report.p99_ns / 1'000.0);
      std::fprintf(f, "    \"p99_9\": %.6f\n", report.p99_9_ns / 1'000.0);
      std::fprintf(f, "  },\n");
      if (report.has_fit()) {
        std::fprintf(f, "  \"distribution_fit\": {\n");
        std::fprintf(f, "    \"name\": \"%s\",\n", json_escape(report.best_fit.name).c_str());
        std::fprintf(f, "    \"ks_statistic\": %.6f,\n", report.best_fit.ks_statistic);
        std::fprintf(f, "    \"ks_pvalue\": %.6f,\n", report.best_fit.ks_pvalue);
        std::fprintf(f, "    \"params\": [");
        for (std::size_t i = 0; i < report.best_fit.params.size(); ++i) {
          std::fprintf(f, "%.10g", report.best_fit.params[i]);
          if (i + 1 < report.best_fit.params.size()) {
            std::fprintf(f, ", ");
          }
        }
        std::fprintf(f, "]\n  },\n");
      } else {
        std::fprintf(f, "  \"distribution_fit\": null,\n");
      }
      std::fprintf(f, "  \"outliers\": {\n");
      std::fprintf(f, "    \"iqr_count\": %lld,\n",
                   static_cast<long long>(report.outliers.iqr_count));
      std::fprintf(f, "    \"iqr_fence_low_ns\": %.6f,\n", report.outliers.iqr_fence_low);
      std::fprintf(f, "    \"iqr_fence_high_ns\": %.6f,\n", report.outliers.iqr_fence_high);
      std::fprintf(f, "    \"modified_z_count\": %lld,\n",
                   static_cast<long long>(report.outliers.modified_z_count));
      std::fprintf(f, "    \"modified_z_threshold\": %.1f\n", report.outliers.modified_z_threshold);
      std::fprintf(f, "  },\n");
      std::fprintf(f, "  \"confidence_intervals_95_ns\": {\n");
      std::fprintf(f, "    \"mean\": [%.6f, %.6f],\n", report.mean_ci_low_ns,
                   report.mean_ci_high_ns);
      std::fprintf(f, "    \"median\": [%.6f, %.6f]\n", report.median_ci_low_ns,
                   report.median_ci_high_ns);
      std::fprintf(f, "  }\n");
      std::fprintf(f, "}\n");
      std::fclose(f);
    }
  }

  {
    std::FILE* f = std::fopen(text_path.c_str(), "w");
    if (f) {
      std::fputs(render_report(report).c_str(), f);
      std::fclose(f);
    }
  }

  return {json_path, text_path};
}

}  // namespace volpulse::latency
