// ─────────────────────────────────────────────────────────────────────────────
// Ingestion service configuration.
//
// The C++ service is configured through a flat `key = value` file and/or
// command line flags. The format is deliberately trivial: the service is a
// long-running daemon whose configuration is mounted into a container, and a
// dependency-free parser removes a whole class of startup failures.
//
// Precedence: command line flags override file values override defaults.
// ─────────────────────────────────────────────────────────────────────────────
#pragma once

#include <cstddef>
#include <filesystem>
#include <string>
#include <vector>

namespace volpulse::ingestion {

/// Runtime configuration of the ingestion engine.
struct IngestionConfig {
  /// Underlying symbols to poll.
  std::vector<std::string> symbols;

  /// Path of the binary audit log.
  std::filesystem::path binary_log_path{"var/binary-logs/options.vlog"};

  /// Replay source: a flat NDJSON file of provider payloads.
  /// Empty means "poll the upstream provider" (production mode).
  std::filesystem::path replay_source;

  /// Maximum number of quotes pulled from the source per poll.
  std::size_t max_batch{512};

  /// Seconds to wait between polls when the source has no data.
  double poll_interval_seconds{1.0};

  /// When true the pipeline never writes to the audit log.
  bool dry_run{true};

  /// Load defaults, then the file (when given), then the command line.
  [[nodiscard]] static IngestionConfig from_args(int argc, char** argv);

  /// Parse a flat `key = value` configuration file.
  [[nodiscard]] static IngestionConfig from_file(const std::filesystem::path& path);

  /// Apply a single `key = value` pair.
  void apply(const std::string& key, const std::string& value);

  /// Reject a configuration that cannot be served.
  /// \throws std::runtime_error with an actionable message.
  void validate() const;

  /// Render the effective configuration for the startup log line.
  [[nodiscard]] std::string describe() const;
};

}  // namespace volpulse::ingestion
