// ─────────────────────────────────────────────────────────────────────────────
// Quote wire codec.
//
// The normalised quote has to be persisted in the binary audit log and later
// handed to the analytics engine. The protobuf contract in `contracts/` is
// the *inter-service* format; this codec is the *on-disk* format, and it is
// intentionally fixed-width and endian-explicit so that a log file written
// on one machine can always be decoded on another.
//
// Layout (little endian, 104 bytes):
//   magic | version | reserved | timestamp_ns | strike | bid | ask | last | iv
//   | contract_id[32] | underlying_symbol[16]
// ─────────────────────────────────────────────────────────────────────────────
#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <string>

#include "volpulse/ingestion/pipeline.h"

namespace volpulse::ingestion {

/// 'VPQ0' as a little-endian uint32.
inline constexpr std::uint32_t kQuoteCodecMagic = 0x30505156U;

/// Bumped on any incompatible layout change.
inline constexpr std::uint16_t kQuoteCodecVersion = 1;

/// Maximum length of a contract identifier, including the terminator.
inline constexpr std::size_t kMaxContractIdLength = 32;

/// Maximum length of an underlying symbol, including the terminator.
inline constexpr std::size_t kMaxSymbolLength = 16;

/// Fixed-width on-disk representation of a quote.
#pragma pack(push, 1)
struct QuoteRecord {
  std::uint32_t magic;
  std::uint16_t version;
  std::uint16_t reserved;
  std::int64_t timestamp_ns;
  double strike;
  double bid;
  double ask;
  double last;
  double implied_volatility;
  char contract_id[kMaxContractIdLength];
  char underlying_symbol[kMaxSymbolLength];
};
#pragma pack(pop)

static_assert(sizeof(QuoteRecord) == 104, "QuoteRecord layout is part of the log format");
static_assert(offsetof(QuoteRecord, strike) == 16,
              "QuoteRecord doubles must stay 8-byte aligned inside the record");

/// Encode `quote` into `out`.
/// \return A span over the encoded bytes.
[[nodiscard]] std::span<const std::byte> encode_quote(const Quote& quote, QuoteRecord& out) noexcept;

/// Decode a quote previously produced by `encode_quote`.
/// \return false when the magic, version or framing is invalid.
[[nodiscard]] bool decode_quote(std::span<const std::byte> bytes, Quote& out) noexcept;

}  // namespace volpulse::ingestion
