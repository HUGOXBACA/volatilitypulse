// ─────────────────────────────────────────────────────────────────────────────
// C++ latency benchmarks for the VolPulse ingestion engine.
//
// Measures the hot paths in the binary audit log and quote codec using the
// Boost-based latency measurement library, and writes JSON + text reports to
// var/artifacts/.
//
//   cmake --build --preset dev --target volpulse_latency_benchmarks
//   ./build/bin/volpulse_latency_benchmarks
// ─────────────────────────────────────────────────────────────────────────────
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <string>
#include <vector>

#include "volpulse/binarylog/format.h"
#include "volpulse/binarylog/reader.h"
#include "volpulse/binarylog/writer.h"
#include "volpulse/ingestion/quote_codec.h"
#include "volpulse/latency/analysis.h"
#include "volpulse/latency/collector.h"
#include "volpulse/latency/report.h"

using volpulse::latency::analyze;
using volpulse::latency::LatencyCollector;
using volpulse::latency::LatencyReport;
using volpulse::latency::Sample;
using volpulse::latency::write_report;

namespace {

int g_failures = 0;

[[nodiscard]] bool gate(const char* name, double ops_per_second, double floor_ops_per_second) {
  const bool ok = ops_per_second >= floor_ops_per_second;
  std::printf("  %-46s %13.0f ops/s  %s\n", name, ops_per_second,
              ok ? "PASS" : "FAIL (floor %.0f)");
  if (!ok) {
    ++g_failures;
  }
  return ok;
}

}  // namespace

int main() {
  using volpulse::binarylog::kDefaultMapCapacity;
  using volpulse::ingestion::decode_quote;
  using volpulse::ingestion::encode_quote;
  using volpulse::ingestion::Quote;
  using volpulse::ingestion::QuoteRecord;

  std::filesystem::remove_all("/tmp/vp_latency_bench");
  std::filesystem::create_directories("/tmp/vp_latency_bench");
  std::filesystem::create_directories("var/artifacts");

  std::printf("======================================================================\n");
  std::printf("VolPulse C++ latency benchmarks\n");
  std::printf("======================================================================\n\n");

  const std::size_t n = 50'000;
  const std::size_t warmup = 1'000;

  // ── Binary log append (100 B payload) ─────────────────────────────────
  {
    const std::filesystem::path path = "/tmp/vp_latency_bench/append100.vlog";
    std::error_code ec;
    std::filesystem::remove(path, ec);

    volpulse::binarylog::MappedWriter writer(path, kDefaultMapCapacity);
    std::vector<std::byte> payload(100);
    for (std::size_t i = 0; i < payload.size(); ++i) {
      payload[i] = static_cast<std::byte>(i % 256);
    }

    LatencyCollector collector(warmup);
    auto sampled = collector.sample("binarylog_append_100B", n, [&] {
      (void)writer.append(payload, 1'700'000'000'000'000'000LL);
    });
    const auto report = analyze(sampled, warmup, true, true, 10'000);
    write_report(report, "var/artifacts");

    std::printf(
      "binarylog_append_100B   p50=%s p99=%s p99.9=%s mean=%s "
      "ops/s=%.0f\n",
      volpulse::latency::detail::fmt_ns(report.p50_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.p99_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.p99_9_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.mean_ns).c_str(), n / (report.mean_ns / 1e9 * n));
    gate("binarylog_append_100B floor", n / (report.mean_ns / 1e9 * n), 500'000.0);
  }

  // ── Binary log append (104 B quote payload) ───────────────────────────
  {
    const std::filesystem::path path = "/tmp/vp_latency_bench/append104.vlog";
    std::error_code ec;
    std::filesystem::remove(path, ec);

    volpulse::binarylog::MappedWriter writer(path, kDefaultMapCapacity);
    std::vector<std::byte> payload(104);
    for (std::size_t i = 0; i < payload.size(); ++i) {
      payload[i] = static_cast<std::byte>(i % 256);
    }

    LatencyCollector collector(warmup);
    auto sampled = collector.sample("binarylog_append_104B", n, [&] {
      (void)writer.append(payload, 1'700'000'000'000'000'000LL);
    });
    const auto report = analyze(sampled, warmup, true, true, 10'000);
    write_report(report, "var/artifacts");

    std::printf(
      "binarylog_append_104B   p50=%s p99=%s p99.9=%s mean=%s "
      "ops/s=%.0f\n",
      volpulse::latency::detail::fmt_ns(report.p50_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.p99_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.p99_9_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.mean_ns).c_str(), n / (report.mean_ns / 1e9 * n));
    gate("binarylog_append_104B floor", n / (report.mean_ns / 1e9 * n), 500'000.0);
  }

  // ── Quote codec encode ────────────────────────────────────────────────
  {
    Quote quote{"opt-abc-123", "AAPL", 187.5, 3.25, 3.30, 3.28, 0.31, 1'700'000'000'000'000'000LL};
    QuoteRecord record{};

    LatencyCollector collector(warmup);
    auto sampled =
      collector.sample("quote_codec_encode", n, [&] { (void)encode_quote(quote, record); });
    const auto report = analyze(sampled, warmup, true, true, 10'000);
    write_report(report, "var/artifacts");

    std::printf(
      "quote_codec_encode      p50=%s p99=%s p99.9=%s mean=%s "
      "ops/s=%.0f\n",
      volpulse::latency::detail::fmt_ns(report.p50_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.p99_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.p99_9_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.mean_ns).c_str(), n / (report.mean_ns / 1e9 * n));
    gate("quote_codec_encode floor", n / (report.mean_ns / 1e9 * n), 2'000'000.0);
  }

  // ── Quote codec decode ────────────────────────────────────────────────
  {
    Quote quote{"opt-abc-123", "AAPL", 187.5, 3.25, 3.30, 3.28, 0.31, 1'700'000'000'000'000'000LL};
    QuoteRecord record{};
    const auto encoded = encode_quote(quote, record);
    Quote decoded{};

    LatencyCollector collector(warmup);
    auto sampled =
      collector.sample("quote_codec_decode", n, [&] { (void)decode_quote(encoded, decoded); });
    const auto report = analyze(sampled, warmup, true, true, 10'000);
    write_report(report, "var/artifacts");

    std::printf(
      "quote_codec_decode      p50=%s p99=%s p99.9=%s mean=%s "
      "ops/s=%.0f\n",
      volpulse::latency::detail::fmt_ns(report.p50_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.p99_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.p99_9_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.mean_ns).c_str(), n / (report.mean_ns / 1e9 * n));
    gate("quote_codec_decode floor", n / (report.mean_ns / 1e9 * n), 2'000'000.0);
  }

  // ── Binary log read (full scan) ───────────────────────────────────────
  {
    const std::filesystem::path path = "/tmp/vp_latency_bench/read.vlog";
    std::error_code ec;
    std::filesystem::remove(path, ec);

    volpulse::binarylog::MappedWriter writer(path, kDefaultMapCapacity);
    std::vector<std::byte> payload(100);
    for (std::size_t i = 0; i < 100'000; ++i) {
      (void)writer.append(payload, 1'700'000'000'000'000'000LL + static_cast<std::int64_t>(i));
    }
    writer.sync();

    volpulse::binarylog::MappedReader reader(path);
    const auto& records = reader.records();
    std::size_t idx = 0;

    LatencyCollector collector(warmup);
    auto sampled = collector.sample("binarylog_read_100B", n, [&] {
      const auto& rec = records[idx % records.size()];
      volatile std::byte sink = rec.payload[0];
      for (std::size_t j = 1; j < rec.payload.size(); ++j) {
        sink = static_cast<std::byte>(sink ^ rec.payload[j]);
      }
      (void)sink;
      ++idx;
    });
    const auto report = analyze(sampled, warmup, true, true, 10'000);
    write_report(report, "var/artifacts");

    std::printf(
      "binarylog_read_100B     p50=%s p99=%s p99.9=%s mean=%s "
      "ops/s=%.0f\n",
      volpulse::latency::detail::fmt_ns(report.p50_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.p99_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.p99_9_ns).c_str(),
      volpulse::latency::detail::fmt_ns(report.mean_ns).c_str(), n / (report.mean_ns / 1e9 * n));
    gate("binarylog_read_100B floor", n / (report.mean_ns / 1e9 * n), 1'000'000.0);
  }

  // ── Summary ───────────────────────────────────────────────────────────
  std::printf("\n======================================================================\n");
  if (g_failures == 0) {
    std::printf("All C++ latency regression gates passed.\n");
    return EXIT_SUCCESS;
  }
  std::printf("%d C++ latency regression gate(s) failed.\n", g_failures);
  return EXIT_FAILURE;
}
