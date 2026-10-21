// ─────────────────────────────────────────────────────────────────────────────
// VolPulse ingestion engine — entry point.
//
//   volpulse-ingestion --config config/ingestion.yaml
//
// The process owns exactly three things: a quote source, a sink and the run
// loop. Shutdown is graceful: SIGINT/SIGTERM set a stop flag, the loop
// drains the current batch, flushes the audit log and exits with status 0.
// ─────────────────────────────────────────────────────────────────────────────
#include <atomic>
#include <csignal>
#include <exception>
#include <filesystem>
#include <iostream>
#include <string>

#include "volpulse/ingestion/config.h"
#include "volpulse/ingestion/ndjson_source.h"
#include "volpulse/ingestion/pipeline.h"

namespace {

std::atomic_bool g_stop_requested{false};

extern "C" void handle_signal(int signal_number) {
  (void)signal_number;
  g_stop_requested.store(true, std::memory_order_relaxed);
}

void install_signal_handlers() {
  std::signal(SIGINT, handle_signal);
  std::signal(SIGTERM, handle_signal);
  std::signal(SIGPIPE, SIG_IGN);
}

}  // namespace

int main(int argc, char** argv) {
  using volpulse::ingestion::BinaryLogSink;
  using volpulse::ingestion::IngestionConfig;
  using volpulse::ingestion::NdjsonQuoteSource;
  using volpulse::ingestion::NullSink;
  using volpulse::ingestion::Pipeline;

  install_signal_handlers();

  try {
    IngestionConfig config = IngestionConfig::from_args(argc, argv);
    config.validate();

    std::cout << "volpulse-ingestion starting: " << config.describe() << std::endl;

    if (!config.replay_source.empty()) {
      NdjsonQuoteSource source(config.replay_source);
      if (config.dry_run) {
        NullSink sink;
        Pipeline pipeline(source, sink, config);
        const auto stats = pipeline.run(g_stop_requested);
        std::cout << "ingestion complete (dry-run): " << stats.quotes_written << " quotes in "
                  << stats.batches << " batches, " << stats.elapsed_seconds << "s" << std::endl;
        return 0;
      }
      BinaryLogSink sink(config.binary_log_path);
      Pipeline pipeline(source, sink, config);
      const auto stats = pipeline.run(g_stop_requested);
      std::cout << "ingestion complete: " << stats.quotes_written << " quotes in " << stats.batches
                << " batches, " << stats.elapsed_seconds << "s, audit log "
                << config.binary_log_path.string() << std::endl;
      return 0;
    }

    std::cerr << "volpulse-ingestion: live polling is not wired up in this build; "
              << "use --replay <file> to exercise the pipeline" << std::endl;
    return 2;
  } catch (const std::exception& error) {
    std::cerr << "volpulse-ingestion: fatal: " << error.what() << std::endl;
    return 1;
  }
}
