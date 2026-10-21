// ─────────────────────────────────────────────────────────────────────────────
// Flat NDJSON replay source implementation.
// ─────────────────────────────────────────────────────────────────────────────
#include "volpulse/ingestion/ndjson_source.h"

#include <cctype>
#include <charconv>
#include <string_view>

namespace volpulse::ingestion {
namespace {

[[nodiscard]] std::string_view trim(std::string_view value) {
  const auto is_space = [](unsigned char c) { return std::isspace(c) != 0; };
  while (!value.empty() && is_space(static_cast<unsigned char>(value.front()))) {
    value.remove_prefix(1);
  }
  while (!value.empty() && is_space(static_cast<unsigned char>(value.back()))) {
    value.remove_suffix(1);
  }
  return value;
}

/// Find `"key"` in a flat JSON object and return the value that follows it.
/// \return An empty view when the key is absent.
[[nodiscard]] std::string_view find_member(std::string_view line, std::string_view key) {
  const std::string needle = "\"" + std::string(key) + "\"";
  const auto position = line.find(needle);
  if (position == std::string_view::npos) {
    return {};
  }
  auto cursor = line.find(':', position + needle.size());
  if (cursor == std::string_view::npos) {
    return {};
  }
  ++cursor;
  while (cursor < line.size() && std::isspace(static_cast<unsigned char>(line[cursor])) != 0) {
    ++cursor;
  }
  if (cursor >= line.size()) {
    return {};
  }
  if (line[cursor] == '"') {
    const auto end = line.find('"', cursor + 1);
    if (end == std::string_view::npos) {
      return {};
    }
    return line.substr(cursor + 1, end - cursor - 1);
  }
  const auto end = line.find_first_of(",}", cursor);
  if (end == std::string_view::npos) {
    return line.substr(cursor);
  }
  return trim(line.substr(cursor, end - cursor));
}

[[nodiscard]] double parse_number(std::string_view text, double fallback = 0.0) {
  if (text.empty()) {
    return fallback;
  }
  double value = 0.0;
  const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
  if (result.ec != std::errc{}) {
    return fallback;
  }
  return value;
}

[[nodiscard]] std::int64_t parse_integer(std::string_view text, std::int64_t fallback = 0) {
  if (text.empty()) {
    return fallback;
  }
  std::int64_t value = 0;
  const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
  if (result.ec != std::errc{}) {
    return fallback;
  }
  return value;
}

}  // namespace

NdjsonQuoteSource::NdjsonQuoteSource(const std::filesystem::path& path)
    : path_(path), stream_(path) {
  if (!stream_) {
    throw std::runtime_error("cannot open replay source: " + path.string());
  }
}

std::vector<Quote> NdjsonQuoteSource::fetch(std::size_t max_quotes) {
  std::vector<Quote> batch;
  batch.reserve(max_quotes);

  std::string line;
  while (batch.size() < max_quotes && std::getline(stream_, line)) {
    ++line_number_;
    const std::string_view trimmed = trim(line);
    if (trimmed.empty() || trimmed.front() == '#') {
      continue;
    }
    Quote quote;
    if (parse_line(trimmed, quote)) {
      batch.push_back(std::move(quote));
    }
  }

  if (batch.empty() && stream_.eof()) {
    exhausted_ = true;
  }
  return batch;
}

bool NdjsonQuoteSource::exhausted() const {
  return exhausted_ || stream_.eof();
}

std::string NdjsonQuoteSource::describe() const {
  return "ndjson:" + path_.string();
}

bool NdjsonQuoteSource::parse_line(std::string_view line, Quote& quote) const {
  quote.contract_id = std::string(find_member(line, "contract_id"));
  quote.underlying_symbol = std::string(find_member(line, "underlying_symbol"));
  if (quote.contract_id.empty() || quote.underlying_symbol.empty()) {
    return false;
  }

  quote.strike = parse_number(find_member(line, "strike"));
  quote.bid = parse_number(find_member(line, "bid"));
  quote.ask = parse_number(find_member(line, "ask"));
  quote.last = parse_number(find_member(line, "last"));
  quote.implied_volatility = parse_number(find_member(line, "implied_volatility"));
  quote.timestamp_ns = parse_integer(find_member(line, "timestamp_ns"));
  return true;
}

}  // namespace volpulse::ingestion
