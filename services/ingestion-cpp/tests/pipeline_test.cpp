// ─────────────────────────────────────────────────────────────────────────────
// Unit tests for the ingestion pipeline: configuration, quote codec and the
// run loop against a temporary binary log.
// ─────────────────────────────────────────────────────────────────────────────
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "volpulse/binarylog/reader.h"
#include "volpulse/ingestion/config.h"
#include "volpulse/ingestion/ndjson_source.h"
#include "volpulse/ingestion/pipeline.h"
#include "volpulse/ingestion/quote_codec.h"

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

std::filesystem::path temp_dir() {
  const auto path = std::filesystem::temp_directory_path() / "volpulse-ingestion-test";
  std::filesystem::remove_all(path);
  std::filesystem::create_directories(path);
  return path;
}

/// Source that yields a fixed number of quotes and then reports exhaustion.
class FixedQuoteSource final : public volpulse::ingestion::QuoteSource {
 public:
  explicit FixedQuoteSource(std::size_t count) : remaining_(count) {}

  std::vector<volpulse::ingestion::Quote> fetch(std::size_t max_quotes) override {
    std::vector<volpulse::ingestion::Quote> batch;
    while (batch.size() < max_quotes && remaining_ > 0) {
      volpulse::ingestion::Quote quote;
      quote.contract_id = "contract-" + std::to_string(remaining_);
      quote.underlying_symbol = "AAPL";
      quote.strike = 100.0 + static_cast<double>(remaining_);
      quote.bid = 1.25;
      quote.ask = 1.30;
      quote.last = 1.27;
      quote.implied_volatility = 0.28;
      quote.timestamp_ns = 1'700'000'000'000'000'000LL;
      batch.push_back(quote);
      --remaining_;
    }
    return batch;
  }

  bool exhausted() const override { return remaining_ == 0; }
  std::string describe() const override { return "fixed"; }

 private:
  std::size_t remaining_;
};

void test_config_parsing() {
  const auto dir = temp_dir();
  const auto path = dir / "ingestion.conf";
  {
    std::ofstream stream(path);
    stream << "# comment\n";
    stream << "symbols = AAPL, MSFT , SPY\n";
    stream << "max_batch = 128\n";
    stream << "poll_interval = 2.5\n";
    stream << "dry_run = false\n";
    stream << "binary_log = var/logs/quotes.vlog\n";
  }

  const auto config = volpulse::ingestion::IngestionConfig::from_file(path);
  CHECK(config.symbols.size() == 3);
  CHECK(config.symbols[0] == "AAPL");
  CHECK(config.symbols[2] == "SPY");
  CHECK(config.max_batch == 128);
  CHECK(config.poll_interval_seconds == 2.5);
  CHECK(config.dry_run == false);
  CHECK(config.binary_log_path == std::filesystem::path("var/logs/quotes.vlog"));

  std::filesystem::remove_all(dir);
}

void test_config_rejects_unknown_key() {
  bool threw = false;
  try {
    volpulse::ingestion::IngestionConfig config;
    config.apply("nonsense", "1");
  } catch (const std::exception&) {
    threw = true;
  }
  CHECK(threw);
}

void test_quote_codec_round_trip() {
  volpulse::ingestion::Quote quote;
  quote.contract_id = "opt-abc-123";
  quote.underlying_symbol = "AAPL";
  quote.strike = 187.5;
  quote.bid = 3.25;
  quote.ask = 3.30;
  quote.last = 3.28;
  quote.implied_volatility = 0.31;
  quote.timestamp_ns = 1'700'000'000'000'000'123LL;

  volpulse::ingestion::QuoteRecord record{};
  const auto bytes = volpulse::ingestion::encode_quote(quote, record);

  volpulse::ingestion::Quote decoded;
  CHECK(volpulse::ingestion::decode_quote(bytes, decoded));
  CHECK(decoded.contract_id == quote.contract_id);
  CHECK(decoded.underlying_symbol == quote.underlying_symbol);
  CHECK(decoded.strike == quote.strike);
  CHECK(decoded.bid == quote.bid);
  CHECK(decoded.ask == quote.ask);
  CHECK(decoded.last == quote.last);
  CHECK(decoded.implied_volatility == quote.implied_volatility);
  CHECK(decoded.timestamp_ns == quote.timestamp_ns);
}

void test_pipeline_writes_readable_log() {
  const auto dir = temp_dir();
  const auto log_path = dir / "quotes.vlog";

  volpulse::ingestion::IngestionConfig config;
  config.max_batch = 4;
  config.dry_run = false;

  FixedQuoteSource source(10);
  volpulse::ingestion::BinaryLogSink sink(log_path);
  volpulse::ingestion::Pipeline pipeline(source, sink, config);

  std::atomic_bool stop{false};
  const auto stats = pipeline.run(stop);
  CHECK(stats.quotes_written == 10);
  CHECK(stats.batches == 3);

  volpulse::binarylog::MappedReader reader(log_path);
  CHECK(reader.records().size() == 10);

  volpulse::ingestion::Quote decoded;
  const auto payload = reader.records()[0].payload;
  CHECK(volpulse::ingestion::decode_quote(payload, decoded));
  CHECK(decoded.underlying_symbol == "AAPL");
  CHECK(decoded.implied_volatility == 0.28);

  std::filesystem::remove_all(dir);
}

void test_ndjson_source() {
  const auto dir = temp_dir();
  const auto path = dir / "quotes.ndjson";
  {
    std::ofstream stream(path);
    stream << R"({"contract_id":"c1","underlying_symbol":"MSFT","strike":400.0,"bid":2.0,"ask":2.1,"last":2.05,"implied_volatility":0.22,"timestamp_ns":1700000000000000000})" << '\n';
    stream << "# a comment line\n";
    stream << R"({"contract_id":"c2","underlying_symbol":"MSFT","strike":410.0,"bid":2.4,"ask":2.5,"last":2.45,"implied_volatility":0.23,"timestamp_ns":1700000000000000001})" << '\n';
  }

  volpulse::ingestion::NdjsonQuoteSource source(path);
  const auto batch = source.fetch(10);
  CHECK(batch.size() == 2);
  CHECK(batch[0].contract_id == "c1");
  CHECK(batch[1].strike == 410.0);
  CHECK(source.exhausted());

  std::filesystem::remove_all(dir);
}

}  // namespace

int main() {
  test_config_parsing();
  test_config_rejects_unknown_key();
  test_quote_codec_round_trip();
  test_pipeline_writes_readable_log();
  test_ndjson_source();

  std::printf("ingestion: %d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
