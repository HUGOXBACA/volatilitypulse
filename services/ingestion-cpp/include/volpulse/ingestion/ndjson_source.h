// ─────────────────────────────────────────────────────────────────────────────
// Flat NDJSON replay source.
//
// Reads provider payloads from a newline-delimited JSON file and normalises
// them into `Quote` values. This is the offline path: it powers replay, the
// determinism tests and the local demo without touching the network.
//
// The parser understands a flat JSON object — string and number members at
// the top level — which is exactly the shape of a normalised provider record.
// The production upstream client lives in `rest_source.{h,cpp}`; this file
// intentionally does not depend on a JSON library.
// ─────────────────────────────────────────────────────────────────────────────
#pragma once

#include <cstddef>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>
#include <vector>

#include "volpulse/ingestion/pipeline.h"

namespace volpulse::ingestion {

/// Reads quotes from a flat NDJSON file.
class NdjsonQuoteSource final : public QuoteSource {
 public:
  explicit NdjsonQuoteSource(const std::filesystem::path& path);

  [[nodiscard]] std::vector<Quote> fetch(std::size_t max_quotes) override;
  [[nodiscard]] bool exhausted() const override;
  [[nodiscard]] std::string describe() const override;

 private:
  /// Parse one NDJSON line into a quote.
  /// \return true when the line yielded a quote.
  bool parse_line(std::string_view line, Quote& quote) const;

  std::filesystem::path path_;
  std::ifstream stream_;
  std::size_t line_number_{0};
  bool exhausted_{false};
};

}  // namespace volpulse::ingestion
