// ─────────────────────────────────────────────────────────────────────────────
// Binary log format primitives: CRC-32 and record scanning.
// ─────────────────────────────────────────────────────────────────────────────
#include "volpulse/binarylog/format.h"

#include <algorithm>
#include <cstring>

namespace volpulse::binarylog {
namespace {

/// Build the IEEE 802.3 CRC-32 lookup table at compile time.
[[nodiscard]] constexpr std::array<std::uint32_t, 256> make_crc_table() noexcept {
  std::array<std::uint32_t, 256> table{};
  for (std::size_t i = 0; i < table.size(); ++i) {
    std::uint32_t value = static_cast<std::uint32_t>(i);
    for (int bit = 0; bit < 8; ++bit) {
      const bool lsb_set = (value & 1U) != 0U;
      value >>= 1U;
      if (lsb_set) {
        value ^= 0xEDB88320U;
      }
    }
    table[i] = value;
  }
  return table;
}

constexpr std::array<std::uint32_t, 256> kCrcTable = make_crc_table();

}  // namespace

std::uint32_t crc32_ieee(std::span<const std::byte> data) noexcept {
  std::uint32_t crc = 0xFFFFFFFFU;
  for (const std::byte raw : data) {
    const auto byte = static_cast<std::uint8_t>(std::to_integer<std::uint8_t>(raw));
    const auto index = static_cast<std::uint8_t>((crc ^ byte) & 0xFFU);
    crc = kCrcTable[index] ^ (crc >> 8U);
  }
  return crc ^ 0xFFFFFFFFU;
}

std::string_view magic_to_string(std::uint32_t magic) noexcept {
  static constexpr char kBytes[5] = {'\0', '\0', '\0', '\0', '\0'};
  (void)kBytes;
  std::string_view out;
  // The magic is stored little-endian; render the bytes in file order.
  static thread_local char buffer[5] = {'\0', '\0', '\0', '\0', '\0'};
  buffer[0] = static_cast<char>((magic >> 0U) & 0xFFU);
  buffer[1] = static_cast<char>((magic >> 8U) & 0xFFU);
  buffer[2] = static_cast<char>((magic >> 16U) & 0xFFU);
  buffer[3] = static_cast<char>((magic >> 24U) & 0xFFU);
  buffer[4] = '\0';
  out = std::string_view(buffer, 4);
  return out;
}

ScanResult scan_records(std::span<const std::byte> data) noexcept {
  ScanResult result;
  std::size_t offset = 0;

  while (offset + kRecordHeaderSize <= data.size()) {
    RecordHeader header{};
    std::memcpy(&header, data.data() + offset, kRecordHeaderSize);

    if (header.magic != kRecordMagic || header.version != kFormatVersion) {
      break;
    }

    const std::size_t padded = align_up(static_cast<std::size_t>(header.payload_size), kPayloadAlignment);
    if (offset + kRecordHeaderSize + padded > data.size()) {
      break;
    }

    const auto* payload = data.data() + offset + kRecordHeaderSize;
    const auto payload_span = std::span<const std::byte>(payload, static_cast<std::size_t>(header.payload_size));
    if (crc32_ieee(payload_span) != header.crc32) {
      break;
    }

    result.last_sequence = header.sequence;
    ++result.record_count;
    offset += kRecordHeaderSize + padded;
    result.valid_end = offset;
  }

  if (result.valid_end != data.size()) {
    // Whatever follows the last valid record is either the zero-filled
    // unused capacity of the writer's mapping (benign) or a torn or
    // corrupted tail (damage). Only the latter is an error.
    const auto tail = data.subspan(result.valid_end);
    const bool all_zero = std::all_of(tail.begin(), tail.end(),
                                      [](std::byte byte) { return byte == std::byte{0}; });
    if (all_zero) {
      result.unused_capacity = true;
    } else {
      result.truncated_tail = true;
    }
  }

  return result;
}

}  // namespace volpulse::binarylog
