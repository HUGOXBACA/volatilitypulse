// ─────────────────────────────────────────────────────────────────────────────
// Quote wire codec implementation.
// ─────────────────────────────────────────────────────────────────────────────
#include "volpulse/ingestion/quote_codec.h"

#include <algorithm>
#include <cstring>

namespace volpulse::ingestion {
namespace {

/// Copy `value` into a fixed-size, NUL-terminated field.
template <std::size_t N>
void copy_field(char (&field)[N], const std::string& value) noexcept {
  const std::size_t count = std::min(value.size(), N - 1U);
  std::memcpy(field, value.data(), count);
  field[count] = '\0';
}

}  // namespace

std::span<const std::byte> encode_quote(const Quote& quote, QuoteRecord& out) noexcept {
  out.magic = kQuoteCodecMagic;
  out.version = kQuoteCodecVersion;
  out.reserved = 0U;
  out.timestamp_ns = quote.timestamp_ns;
  out.strike = quote.strike;
  out.bid = quote.bid;
  out.ask = quote.ask;
  out.last = quote.last;
  out.implied_volatility = quote.implied_volatility;
  copy_field(out.contract_id, quote.contract_id);
  copy_field(out.underlying_symbol, quote.underlying_symbol);

  return std::span<const std::byte>(reinterpret_cast<const std::byte*>(&out), sizeof(QuoteRecord));
}

bool decode_quote(std::span<const std::byte> bytes, Quote& out) noexcept {
  if (bytes.size() < sizeof(QuoteRecord)) {
    return false;
  }

  QuoteRecord record{};
  std::memcpy(&record, bytes.data(), sizeof(QuoteRecord));

  if (record.magic != kQuoteCodecMagic || record.version != kQuoteCodecVersion) {
    return false;
  }

  out.timestamp_ns = record.timestamp_ns;
  out.strike = record.strike;
  out.bid = record.bid;
  out.ask = record.ask;
  out.last = record.last;
  out.implied_volatility = record.implied_volatility;

  const auto* id = std::memchr(record.contract_id, '\0', kMaxContractIdLength);
  out.contract_id.assign(id != nullptr ? record.contract_id
                                       : record.contract_id + kMaxContractIdLength);

  const auto* symbol = std::memchr(record.underlying_symbol, '\0', kMaxSymbolLength);
  out.underlying_symbol.assign(symbol != nullptr ? record.underlying_symbol
                                                 : record.underlying_symbol + kMaxSymbolLength);

  return true;
}

}  // namespace volpulse::ingestion
