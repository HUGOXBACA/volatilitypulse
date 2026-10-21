// ─────────────────────────────────────────────────────────────────────────────
// Binary audit log — on-disk record format.
//
// The log is append-only and memory mapped. Every record is self describing:
//
//   ┌──────────────────────── RecordHeader (32 bytes) ──────────────────────┐
//   │ magic │ ver │ flags │ payload_size │ sequence │ timestamp │ crc32    │
//   └───────────────────────────────────────────────────────────────────────┘
//   ┌────────────────────────── payload (payload_size bytes) ──────────────┐
//   └───────────────────────────────────────────────────────────────────────┘
//   ┌──────────────────── zero padding to an 8-byte boundary ──────────────┐
//   └───────────────────────────────────────────────────────────────────────┘
//
// Invariants:
//   * `magic` and `version` allow a reader to reject foreign data outright.
//   * `crc32` covers the payload only; the header is trusted, the payload
//     is not. A torn tail record is detected and discarded by the scanner.
//   * `sequence` is monotonic and gap-free within a single log file.
//   * Padding is always zeroed so that byte-for-byte log comparison is
//     deterministic.
// ─────────────────────────────────────────────────────────────────────────────
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>

namespace volpulse::binarylog {

/// 'VPLS' read as a little-endian uint32.
inline constexpr std::uint32_t kRecordMagic = 0x534C5056U;

/// Bumped whenever the on-disk layout changes incompatibly.
inline constexpr std::uint16_t kFormatVersion = 1;

/// Size of RecordHeader in bytes.
inline constexpr std::size_t kRecordHeaderSize = 32;

/// Every record starts on an 8-byte boundary.
inline constexpr std::size_t kPayloadAlignment = 8;

/// Default size of the memory-mapped window (64 MiB).
inline constexpr std::size_t kDefaultMapCapacity = 64ULL * 1024ULL * 1024ULL;

/// Flags carried in RecordHeader::flags.
enum class RecordFlags : std::uint16_t {
  kNone = 0,
  /// Payload is compressed (reserved for a future codec).
  kCompressed = 1U << 0U,
  /// Payload is a checkpoint marker, not market data.
  kCheckpoint = 1U << 1U,
};

/// Fixed-size record header. Packed: the layout is part of the file format.
#pragma pack(push, 1)
struct RecordHeader {
  std::uint32_t magic;
  std::uint16_t version;
  std::uint16_t flags;
  std::uint32_t payload_size;
  std::uint64_t sequence;
  std::int64_t timestamp_ns;
  std::uint32_t crc32;
};
#pragma pack(pop)

static_assert(sizeof(RecordHeader) == kRecordHeaderSize,
              "RecordHeader must match the documented 32-byte on-disk layout");
static_assert(offsetof(RecordHeader, payload_size) == 8,
              "RecordHeader field offsets are part of the file format");

/// IEEE 802.3 CRC-32 over `data`.
[[nodiscard]] std::uint32_t crc32_ieee(std::span<const std::byte> data) noexcept;

/// Round `value` up to the next multiple of `alignment` (a power of two).
[[nodiscard]] constexpr std::size_t align_up(std::size_t value, std::size_t alignment) noexcept {
  return (value + alignment - 1U) & ~(alignment - 1U);
}

/// Human readable rendering of the magic bytes, for diagnostics.
[[nodiscard]] std::string_view magic_to_string(std::uint32_t magic) noexcept;

/// Result of walking a byte range looking for valid records.
struct ScanResult {
  /// Offset just past the last valid record.
  std::size_t valid_end = 0;
  /// Sequence number of the last valid record (0 when the log is empty).
  std::uint64_t last_sequence = 0;
  /// Number of valid records found.
  std::uint64_t record_count = 0;
  /// True when trailing bytes are present and are *not* the zero-filled
  /// unused capacity of the mapping — i.e. the log is damaged.
  bool truncated_tail = false;
  /// True when the file is longer than its records because the writer keeps
  /// a mapped window larger than the data written so far.
  bool unused_capacity = false;
};

/// Walk `data` and report the extent of the valid record sequence.
/// Stops at the first header that fails validation, which is exactly the
/// behaviour an append-only writer needs to self-heal a partial tail.
[[nodiscard]] ScanResult scan_records(std::span<const std::byte> data) noexcept;

}  // namespace volpulse::binarylog
