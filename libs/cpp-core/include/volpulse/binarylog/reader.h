// ─────────────────────────────────────────────────────────────────────────────
// Reader for the binary audit log.
//
// The reader is the replay path: given a log file and a byte offset (for
// example the `binary_log_offset` carried in a Kafka envelope) it can
// reconstruct the exact bytes the analytics engine consumed.
// ─────────────────────────────────────────────────────────────────────────────
#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <vector>

#include "volpulse/binarylog/format.h"

namespace volpulse::binarylog {

/// A decoded record: the header plus a view over the payload.
struct RecordView {
  /// Header copied by value: the reader owns it for the lifetime of the
  /// view, so no pointer into a transient buffer can dangle.
  RecordHeader header;
  /// Payload bytes, pointing into the mapped file.
  std::span<const std::byte> payload;
};

/// Memory-mapped reader over a binary log file.
class MappedReader {
 public:
  /// Map `path` read-only and decode every valid record.
  ///
  /// \throws std::filesystem::filesystem_error when the file cannot be opened.
  /// \throws std::runtime_error when the file cannot be mapped.
  explicit MappedReader(const std::filesystem::path& path);

  ~MappedReader();

  MappedReader(MappedReader&& other) noexcept;
  MappedReader& operator=(MappedReader&& other) noexcept;
  MappedReader(const MappedReader&) = delete;
  MappedReader& operator=(const MappedReader&) = delete;

  /// Every valid record in file order.
  [[nodiscard]] const std::vector<RecordView>& records() const noexcept {
    return records_;
  }

  /// Verify the integrity of every record (magic, version, CRC).
  /// \param error Populated with a description of the first failure.
  /// \return true when the whole log is intact.
  [[nodiscard]] bool verify(std::string& error) const;

  /// True when trailing bytes were rejected during the initial scan.
  [[nodiscard]] bool has_truncated_tail() const noexcept {
    return scan_.truncated_tail;
  }

  /// Offset just past the last valid record.
  [[nodiscard]] std::size_t valid_end() const noexcept {
    return scan_.valid_end;
  }

 private:
  void close_window() noexcept;

  std::filesystem::path path_;
  int fd_ = -1;
  void* mapping_ = nullptr;
  std::size_t mapped_size_ = 0;
  std::vector<RecordView> records_;
  ScanResult scan_;
};

}  // namespace volpulse::binarylog
