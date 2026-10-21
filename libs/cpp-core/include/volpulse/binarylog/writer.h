// ─────────────────────────────────────────────────────────────────────────────
// Append-only, memory-mapped binary log writer.
//
// Why memory mapped: the ingestion engine writes one record per quote at
// market rate. A `write(2)` syscall per record would dominate the latency
// budget; an mmap lets the writer place bytes with a plain memcpy and lets
// the kernel flush pages under memory pressure.
//
// Durability model: the log is an *audit trail*, not the system of record.
// Records are ordered and checksummed but only made durable on an explicit
// flush() / sync(). Downstream state lives in the broker and the databases;
// the log exists so that any consumed record can be replayed from disk.
// ─────────────────────────────────────────────────────────────────────────────
#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <span>
#include <string_view>

#include "volpulse/binarylog/format.h"

namespace volpulse::binarylog {

/// Writer for a single append-only binary log file.
///
/// Thread safety: a single writer instance must be used by one thread at a
/// time. The ingestion engine owns exactly one instance and publishes to it
/// from the feed-handler thread only.
class MappedWriter {
 public:
  /// Open (creating if necessary) the log at `path`.
  ///
  /// If the file already contains records they are scanned: the writer
  /// continues after the last valid record and any torn tail is truncated,
  /// so a crash mid-append never poisons the log.
  ///
  /// \throws std::filesystem::filesystem_error on open failure.
  /// \throws std::runtime_error on mapping failure.
  explicit MappedWriter(const std::filesystem::path& path,
                         std::size_t initial_capacity = kDefaultMapCapacity);

  ~MappedWriter();

  MappedWriter(MappedWriter&& other) noexcept;
  MappedWriter& operator=(MappedWriter&& other) noexcept;
  MappedWriter(const MappedWriter&) = delete;
  MappedWriter& operator=(const MappedWriter&) = delete;

  /// Append a payload and return the byte offset of the new record.
  ///
  /// \param payload     Bytes to store verbatim.
  /// \param timestamp_ns Event timestamp of the record, in nanoseconds since
  ///                     the Unix epoch.
  /// \throws std::runtime_error if the mapping cannot be grown.
  [[nodiscard]] std::uint64_t append(std::span<const std::byte> payload,
                                     std::int64_t timestamp_ns);

  /// Convenience overload for string payloads.
  [[nodiscard]] std::uint64_t append(std::string_view text, std::int64_t timestamp_ns);

  /// Push buffered pages to the OS.
  void flush();

  /// Push buffered pages to the OS and fsync the file to stable storage.
  void sync();

  /// Number of bytes logically written (excludes unused capacity).
  [[nodiscard]] std::uint64_t size() const noexcept { return end_offset_; }

  /// Sequence number that the next appended record will receive.
  [[nodiscard]] std::uint64_t sequence() const noexcept { return next_sequence_; }

  /// Path of the log file.
  [[nodiscard]] const std::filesystem::path& path() const noexcept { return path_; }

 private:
  void map_window(std::size_t capacity);
  void grow_to(std::size_t required);
  void close_window() noexcept;
  void close_file() noexcept;

  std::filesystem::path path_;
  int fd_ = -1;
  void* mapping_ = nullptr;
  std::size_t capacity_ = 0;
  std::size_t end_offset_ = 0;
  std::uint64_t next_sequence_ = 0;
};

}  // namespace volpulse::binarylog
