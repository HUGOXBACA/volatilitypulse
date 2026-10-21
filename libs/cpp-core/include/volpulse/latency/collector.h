// ─────────────────────────────────────────────────────────────────────────────
// High-resolution latency sampling for C++.
//
// Uses std::chrono::steady_clock (monotonic, nanosecond resolution where
// available). A warm-up phase runs the callable un-timed before sampling so
// that CPU frequency scaling, branch-predictor state and cold-cache misses
// are amortized rather than measured.
//
// Outliers are not dropped by default: silently discarding tail events
// produces an optimistic and misleading latency picture. Outlier detection is
// available separately in analysis.h.
// ─────────────────────────────────────────────────────────────────────────────
#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace volpulse::latency {

/// A single latency measurement.
struct Sample {
  std::string func_name;    // qualified name of the measured callable
  std::int64_t latency_ns;  // wall-clock latency in nanoseconds
  std::size_t iteration;    // zero-based index within the collection run
};

/// High-resolution latency sampler.
class LatencyCollector {
 public:
  /// Construct a collector.
  /// \param warmup Number of un-timed invocations to perform before sampling.
  explicit LatencyCollector(std::size_t warmup = 100) : warmup_(warmup) {}

  /// Measure \p func latency over \p n timed iterations.
  ///
  /// \tparam Func Callable type.
  /// \tparam Args Argument types.
  /// \param name Display name used in reports.
  /// \param n Number of timed samples to collect (must be >= 1).
  /// \param func Callable to measure.
  /// \param args Arguments forwarded to \p func.
  /// \return One :class:`Sample` per iteration, in collection order.
  template <typename Func, typename... Args>
  [[nodiscard]] std::vector<Sample> sample(std::string_view name, std::size_t n, Func&& func,
                                           Args&&... args) {
    if (n == 0) {
      return {};
    }

    // Warm up: run un-timed so caches, frequency scaling and branch
    // predictor state reach steady state before measurement.
    for (std::size_t i = 0; i < warmup_; ++i) {
      std::invoke(std::forward<Func>(func), std::forward<Args>(args)...);
    }

    std::vector<Sample> samples;
    samples.reserve(n);
    const std::string func_name{name};

    using Clock = std::chrono::steady_clock;
    for (std::size_t i = 0; i < n; ++i) {
      const auto start = Clock::now();
      std::invoke(std::forward<Func>(func), std::forward<Args>(args)...);
      const auto end = Clock::now();
      const auto latency_ns =
        std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
      samples.push_back(Sample{func_name, latency_ns, i});
    }
    return samples;
  }

  [[nodiscard]] std::size_t warmup() const noexcept {
    return warmup_;
  }

 private:
  std::size_t warmup_;
};

}  // namespace volpulse::latency
