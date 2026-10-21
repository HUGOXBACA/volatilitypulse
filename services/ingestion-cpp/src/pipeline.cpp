// ─────────────────────────────────────────────────────────────────────────────
// Ingestion pipeline implementation.
// ─────────────────────────────────────────────────────────────────────────────
#include "volpulse/ingestion/pipeline.h"

#include <chrono>
#include <system_error>
#include <stdexcept>
#include <thread>

#include "volpulse/ingestion/quote_codec.h"

namespace volpulse::ingestion {
namespace {

/// Create the parent directory of `path` before the log file is opened.
std::filesystem::path ensure_parent_directory(const std::filesystem::path& path) {
  const auto parent = path.parent_path();
  if (!parent.empty()) {
    std::error_code error;
    std::filesystem::create_directories(parent, error);
  }
  return path;
}

}  // namespace

BinaryLogSink::BinaryLogSink(const std::filesystem::path& path)
    : writer_(ensure_parent_directory(path)) {}

void BinaryLogSink::write(const Quote& quote) {
  QuoteRecord record{};
  const auto bytes = encode_quote(quote, record);
  (void)writer_.append(bytes, quote.timestamp_ns);
  ++written_;
}

void BinaryLogSink::flush() {
  writer_.sync();
}

void NullSink::write(const Quote& quote) {
  (void)quote;
  ++written_;
}

void NullSink::flush() {}

Pipeline::Pipeline(QuoteSource& source, QuoteSink& sink, IngestionConfig config)
    : source_(source), sink_(sink), config_(std::move(config)) {}

PipelineStats Pipeline::run(const std::atomic_bool& stop_requested) {
  PipelineStats stats{};
  const auto started = std::chrono::steady_clock::now();
  const auto idle_interval =
      std::chrono::duration<double>(config_.poll_interval_seconds);

  while (!stop_requested.load(std::memory_order_relaxed)) {
    std::vector<Quote> batch;
    try {
      batch = source_.fetch(config_.max_batch);
    } catch (const std::exception&) {
      // A source failure must not kill the daemon: the supervisor owns the
      // process lifetime, so back off and retry.
      ++stats.source_errors;
      std::this_thread::sleep_for(
          std::chrono::duration_cast<std::chrono::steady_clock::duration>(idle_interval));
      continue;
    }

    if (batch.empty()) {
      if (source_.exhausted()) {
        break;
      }
      std::this_thread::sleep_for(
          std::chrono::duration_cast<std::chrono::steady_clock::duration>(idle_interval));
      continue;
    }

    for (const Quote& quote : batch) {
      sink_.write(quote);
      ++stats.quotes_written;
    }
    stats.quotes_read += batch.size();
    ++stats.batches;
    sink_.flush();

    if (source_.exhausted()) {
      break;
    }
  }

  sink_.flush();
  stats.elapsed_seconds =
      std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
  return stats;
}

}  // namespace volpulse::ingestion
