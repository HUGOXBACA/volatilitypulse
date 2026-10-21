// ─────────────────────────────────────────────────────────────────────────────
// Benchmarks for the VolPulse ingestion engine and binary audit log.
//
// Compile and run:
//
//   clang++ -std=c++20 -O2 \
//     -Ilibs/cpp-core/include -Iservices/ingestion-cpp/include \
//     libs/cpp-core/src/binarylog/*.cpp \
//     services/ingestion-cpp/src/*.cpp \
//     libs/cpp-core/tests/benchmarks/run_benchmarks.cpp \
//     -o build/benchmarks/volpulse_benchmarks
//
// Numbers are wall-clock per-operation microseconds at the 50th, 95th and 99th
// percentiles, plus operations per second.
// ─────────────────────────────────────────────────────────────────────────────
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <random>
#include <string>
#include <vector>

#include "volpulse/binarylog/format.h"
#include "volpulse/binarylog/reader.h"
#include "volpulse/binarylog/writer.h"
#include "volpulse/ingestion/quote_codec.h"

using namespace std::chrono;

namespace {

using Clock = steady_clock;
using Duration = nanoseconds;

struct Result {
  const char* name = "";
  int ops = 0;
  double total_seconds = 0.0;
  double p50_us = 0.0;
  double p95_us = 0.0;
  double p99_us = 0.0;
  double ops_per_second = 0.0;
};

[[nodiscard]] Result bench(const char* name, int ops, int warmup, auto&& fn) {
  Result result{name, ops, 0.0, 0.0, 0.0, 0.0, 0.0};

  std::vector<double> times;
  times.reserve(ops);

  for (int i = 0; i < warmup; ++i) {
    fn();
  }

  for (int i = 0; i < ops; ++i) {
    const auto start = Clock::now();
    fn();
    const auto end = Clock::now();
    times.push_back(duration_cast<Duration>(end - start).count());
  }

  std::sort(times.begin(), times.end());

  const auto p50 = times[static_cast<std::size_t>(ops * 0.50)];
  const auto p95 = times[static_cast<std::size_t>(ops * 0.95)];
  const auto p99 = times[static_cast<std::size_t>(ops * 0.99)];

  double total = 0.0;
  for (double t : times) {
    total += t;
  }

  result.total_seconds = total / 1e9;
  result.p50_us = p50;
  result.p95_us = p95;
  result.p99_us = p99;
  result.ops_per_second = ops / result.total_seconds;
  return result;
}

[[nodiscard]] std::vector<std::byte> make_payload(int size) {
  std::vector<std::byte> payload(size);
  for (int i = 0; i < size; ++i) {
    payload[i] = static_cast<std::byte>(i % 256);
  }
  return payload;
}

}  // namespace

int main() {
  using volpulse::binarylog::kDefaultMapCapacity;
  using volpulse::ingestion::encode_quote;
  using volpulse::ingestion::Quote;
  using volpulse::ingestion::QuoteRecord;

  std::vector<Result> results;

  // ── Binary log append ───────────────────────────────────────────────
  {
    const std::filesystem::path path =
      std::filesystem::temp_directory_path() / "vpbench_append.vlog";
    std::error_code ec;
    std::filesystem::remove(path, ec);

    volpulse::binarylog::MappedWriter writer(path, kDefaultMapCapacity);
    const auto payload = make_payload(100);

    const auto r = bench("binarylog_append (100 B payload)", 100'000, 1'000,
                         [&] { (void)writer.append(payload, 1'700'000'000'000'000'000LL); });
    results.push_back(r);
  }

  // ── Binary log append (full-width quote) ────────────────────────────
  {
    const std::filesystem::path path =
      std::filesystem::temp_directory_path() / "vpbench_append_quote.vlog";
    std::error_code ec;
    std::filesystem::remove(path, ec);

    volpulse::binarylog::MappedWriter writer(path, kDefaultMapCapacity);
    const auto payload = make_payload(104);

    const auto r = bench("binarylog_append (104 B quote)", 100'000, 1'000,
                         [&] { (void)writer.append(payload, 1'700'000'000'000'000'000LL); });
    results.push_back(r);
  }

  // ── Binary log read ─────────────────────────────────────────────────
  {
    const std::filesystem::path path = std::filesystem::temp_directory_path() / "vpbench_read.vlog";
    std::error_code ec;
    std::filesystem::remove(path, ec);

    volpulse::binarylog::MappedWriter writer(path, kDefaultMapCapacity);
    const auto payload = make_payload(100);
    for (int i = 0; i < 100'000; ++i) {
      (void)writer.append(payload, 1'700'000'000'000'000'000LL + i);
    }
    writer.sync();

    std::vector<double> times;
    times.reserve(100'000);
    {
      volpulse::binarylog::MappedReader reader(path);
      const auto records = reader.records();

      for (int i = 0; i < 100'000 && i < static_cast<int>(records.size()); ++i) {
        const auto start = Clock::now();
        const auto bytes = records[i].payload;
        const auto n = bytes.size();
        volatile std::byte sink = bytes[0];
        for (std::size_t j = 1; j < n; ++j) {
          sink = static_cast<std::byte>(sink ^ bytes[j]);
        }
        (void)sink;
        const auto end = Clock::now();
        times.push_back(duration_cast<Duration>(end - start).count());
      }
    }

    Result r{
      "binarylog_read (100 B payload)", static_cast<int>(times.size()), 0.0, 0.0, 0.0, 0.0, 0.0};
    std::sort(times.begin(), times.end());
    double total = 0.0;
    for (double t : times) {
      total += t;
    }
    r.total_seconds = total / 1e9;
    r.p50_us = times[static_cast<std::size_t>(times.size() * 0.50)];
    r.p95_us = times[static_cast<std::size_t>(times.size() * 0.95)];
    r.p99_us = times[static_cast<std::size_t>(times.size() * 0.99)];
    r.ops_per_second = static_cast<int>(times.size()) / r.total_seconds;
    results.push_back(r);
  }

  // ── Quote codec encode ──────────────────────────────────────────────
  {
    Quote quote{
      "opt-abc-123", "AAPL", 187.5, 3.25, 3.30, 3.28, 0.31, 1'700'000'000'000'000'000LL,
    };
    QuoteRecord record{};

    const auto r =
      bench("quote_codec_encode", 200'000, 2'000, [&] { (void)encode_quote(quote, record); });
    results.push_back(r);
  }

  // ── Quote codec decode ──────────────────────────────────────────────
  {
    Quote quote{
      "opt-abc-123", "AAPL", 187.5, 3.25, 3.30, 3.28, 0.31, 1'700'000'000'000'000'000LL,
    };
    QuoteRecord record{};
    const auto encoded = encode_quote(quote, record);
    Quote decoded{};

    const auto r =
      bench("quote_codec_decode", 200'000, 2'000, [&] { (void)decode_quote(encoded, decoded); });
    results.push_back(r);
  }

  // ── Report ──────────────────────────────────────────────────────────
  printf("\nVolPulse ingestion benchmarks\n");
  printf("==============================\n");
  printf("%-48s %10s %10s %10s %12s\n", "benchmark", "p50 (ns)", "p95 (ns)", "p99 (ns)", "ops/s");
  printf(
    "------------------------------------------------------------"
    "--------------------------------------------\n");

  for (const auto& r : results) {
    printf("%-48s %10.2f %10.2f %10.2f %12.0f\n", r.name, r.p50_us, r.p95_us, r.p99_us,
           r.ops_per_second);
  }

  printf(
    "------------------------------------------------------------"
    "--------------------------------------------\n");

  double total_ops = 0.0;
  double total_time = 0.0;
  for (const auto& r : results) {
    total_ops += r.ops_per_second * r.total_seconds;
    total_time += r.total_seconds;
  }
  printf("%-48s %10s %10s %10s %12.0f\n", "total", "", "", "", total_ops / total_time);

  // Regression gates.
  bool failed = false;
  const struct {
    const char* name;
    double floor_ops_per_second;
  } gates[] = {
    {"binarylog_append (100 B payload)", 200'000},
    {"binarylog_append (104 B quote)", 200'000},
    {"binarylog_read (100 B payload)", 500'000},
    {"quote_codec_encode", 1'000'000},
    {"quote_codec_decode", 1'000'000},
  };

  for (const auto& r : results) {
    for (const auto& gate : gates) {
      if (std::strcmp(r.name, gate.name) == 0 && r.ops_per_second < gate.floor_ops_per_second) {
        printf("REGRESSION: %s at %.0f ops/s < %.0f\n", r.name, r.ops_per_second,
               gate.floor_ops_per_second);
        failed = true;
      }
    }
  }

  if (failed) {
    printf("\n%d regression gate(s) failed.\n", 1);
    return 1;
  }

  printf("\nAll regression gates passed.\n");
  return 0;
}
