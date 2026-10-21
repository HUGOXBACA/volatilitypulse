// ─────────────────────────────────────────────────────────────────────────────
// Unit tests for the C++ latency measurement library.
//
// Self-contained on purpose: runs with nothing but a C++20 compiler and Boost.
// ─────────────────────────────────────────────────────────────────────────────
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "volpulse/latency/analysis.h"
#include "volpulse/latency/collector.h"
#include "volpulse/latency/report.h"

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool condition, const char* expression, const char* file, int line) {
  ++g_checks;
  if (!condition) {
    ++g_failures;
    std::fprintf(stderr, "FAIL %s:%d: %s\n", file, line, expression);
  }
}

#define CHECK(expr) check((expr), #expr, __FILE__, __LINE__)

void test_collector_produces_samples() {
  volpulse::latency::LatencyCollector collector(10);
  auto sink = [](int& x) { x += 1; };
  int state = 0;

  const auto samples = collector.sample("sink", 100, sink, std::ref(state));
  CHECK(samples.size() == 100);
  CHECK(state == 100 + 10);  // 10 warm-up + 100 timed
  for (const auto& s : samples) {
    CHECK(s.func_name == "sink");
    CHECK(s.latency_ns >= 0);
    CHECK(s.iteration < 100);
  }
  CHECK(collector.warmup() == 10);
}

void test_analyze_sane_statistics() {
  // Deterministic-ish data: linear ramp.
  std::vector<volpulse::latency::Sample> samples;
  samples.reserve(1000);
  for (std::size_t i = 0; i < 1000; ++i) {
    samples.push_back(volpulse::latency::Sample{"ramp", static_cast<std::int64_t>(100 + i), i});
  }

  const auto report = volpulse::latency::analyze(samples, 0, true, true, 1000);

  CHECK(report.sample_count == 1000);
  CHECK(report.func_name == "ramp");
  CHECK(report.min_ns <= report.mean_ns);
  CHECK(report.mean_ns <= report.max_ns);
  CHECK(report.p50_ns <= report.p90_ns);
  CHECK(report.p90_ns <= report.p95_ns);
  CHECK(report.p95_ns <= report.p99_ns);
  CHECK(report.p99_ns <= report.p99_9_ns);
  CHECK(report.variance_ns >= 0.0);
  CHECK(report.has_fit());
  CHECK(!report.best_fit.name.empty());
  CHECK(report.best_fit.ks_pvalue >= 0.0 && report.best_fit.ks_pvalue <= 1.0);
  CHECK(report.outliers.iqr_count >= 0);
}

void test_analyze_constant_data() {
  std::vector<volpulse::latency::Sample> samples;
  samples.reserve(100);
  for (std::size_t i = 0; i < 100; ++i) {
    samples.push_back(volpulse::latency::Sample{"const", 500, i});
  }

  const auto report = volpulse::latency::analyze(samples, 0, true, true, 1000);
  CHECK(report.min_ns == 500.0);
  CHECK(report.max_ns == 500.0);
  CHECK(report.mean_ns == 500.0);
  CHECK(report.variance_ns == 0.0);
}

void test_detect_outliers() {
  std::vector<double> data = {100, 101, 102, 103, 104, 1000};  // 1000 is outlier
  const auto out = volpulse::latency::detect_outliers(data);
  CHECK(out.iqr_count >= 1);
  CHECK(out.modified_z_count >= 1);
}

void test_write_report_creates_files() {
  std::vector<volpulse::latency::Sample> samples;
  samples.reserve(200);
  for (std::size_t i = 0; i < 200; ++i) {
    samples.push_back(
      volpulse::latency::Sample{"write_test", static_cast<std::int64_t>(50 + i * 2), i});
  }

  const auto report = volpulse::latency::analyze(samples, 0, true, true, 1000);
  const auto [json_path, text_path] =
    volpulse::latency::write_report(report, "/tmp/vp_latency_test");

  CHECK(!json_path.empty());
  CHECK(!text_path.empty());

  // Verify files exist and contain expected markers.
  std::string json_text;
  {
    std::ifstream stream(json_path);
    std::stringstream buffer;
    buffer << stream.rdbuf();
    json_text = buffer.str();
  }
  CHECK(json_text.find("\"func_name\"") != std::string::npos);
  CHECK(json_text.find("\"percentiles_ns\"") != std::string::npos);
  CHECK(json_text.find("\"outliers\"") != std::string::npos);

  std::string text_text;
  {
    std::ifstream stream(text_path);
    std::stringstream buffer;
    buffer << stream.rdbuf();
    text_text = buffer.str();
  }
  CHECK(text_text.find("Latency report: write_test") != std::string::npos);
  CHECK(text_text.find("Percentiles") != std::string::npos);

  std::filesystem::remove(json_path);
  std::filesystem::remove(text_path);
}

}  // namespace

int main() {
  test_collector_produces_samples();
  test_analyze_sane_statistics();
  test_analyze_constant_data();
  test_detect_outliers();
  test_write_report_creates_files();

  std::printf("latency: %d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
