// ─────────────────────────────────────────────────────────────────────────────
// The ingestion pipeline.
//
//   QuoteSource ──► Pipeline ──► QuoteSink
//
// The pipeline owns the run loop, the pacing, the error handling and the
// counters. It knows nothing about HTTP, Kafka or the binary log format:
// those are supplied through the two interfaces below. That separation is
// what makes the loop testable without a network.
//
// Invariants enforced by the loop:
//   * Quotes are written to the sink in the order the source produced them.
//   * The run loop stops promptly on SIGINT/SIGTERM.
//   * A source failure is retried after `poll_interval_seconds`; it never
//     terminates the process (the supervisor owns process lifetime).
// ─────────────────────────────────────────────────────────────────────────────
#pragma once

#include <atomic>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

#include "volpulse/binarylog/writer.h"
#include "volpulse/ingestion/config.h"

namespace volpulse::ingestion {

/// A normalised quote as produced by the ingestion engine.
struct Quote {
  std::string contract_id;
  std::string underlying_symbol;
  double strike{0.0};
  double bid{0.0};
  double ask{0.0};
  double last{0.0};
  double implied_volatility{0.0};
  std::int64_t timestamp_ns{0};
};

/// Source of normalised quotes.
class QuoteSource {
 public:
  virtual ~QuoteSource() = default;

  /// Fetch up to `max_quotes` quotes.
  /// \throws std::runtime_error on an unrecoverable transport error.
  [[nodiscard]] virtual std::vector<Quote> fetch(std::size_t max_quotes) = 0;

  /// True when the source has no more data and will never produce any.
  [[nodiscard]] virtual bool exhausted() const = 0;

  /// Human readable source description for the startup log line.
  [[nodiscard]] virtual std::string describe() const = 0;
};

/// Destination for normalised quotes.
class QuoteSink {
 public:
  virtual ~QuoteSink() = default;

  /// Persist a single quote.
  virtual void write(const Quote& quote) = 0;

  /// Make everything written so far durable.
  virtual void flush() = 0;
};

/// Sink that appends quotes to the memory-mapped binary audit log.
class BinaryLogSink final : public QuoteSink {
 public:
  explicit BinaryLogSink(const std::filesystem::path& path);

  void write(const Quote& quote) override;
  void flush() override;

  /// Number of quotes written since construction.
  [[nodiscard]] std::uint64_t written() const noexcept { return written_; }

 private:
  binarylog::MappedWriter writer_;
  std::uint64_t written_{0};
};

/// Sink that discards everything. Used by `--dry-run` and by tests.
class NullSink final : public QuoteSink {
 public:
  void write(const Quote& quote) override;
  void flush() override;

  [[nodiscard]] std::uint64_t written() const noexcept { return written_; }

 private:
  std::uint64_t written_{0};
};

/// Counters collected during a pipeline run.
struct PipelineStats {
  std::uint64_t quotes_read{0};
  std::uint64_t quotes_written{0};
  std::uint64_t batches{0};
  std::uint64_t source_errors{0};
  double elapsed_seconds{0.0};
};

/// The ingestion run loop.
class Pipeline {
 public:
  Pipeline(QuoteSource& source, QuoteSink& sink, IngestionConfig config);

  /// Run until the source is exhausted or `stop_requested` is set.
  [[nodiscard]] PipelineStats run(const std::atomic_bool& stop_requested);

 private:
  QuoteSource& source_;
  QuoteSink& sink_;
  IngestionConfig config_;
};

}  // namespace volpulse::ingestion
