// ─────────────────────────────────────────────────────────────────────────────
// Ingestion service configuration implementation.
// ─────────────────────────────────────────────────────────────────────────────
#include "volpulse/ingestion/config.h"

#include <algorithm>
#include <cctype>
#include <charconv>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <system_error>

namespace volpulse::ingestion {
namespace {

[[nodiscard]] std::string trim(std::string_view value) {
  const auto is_space = [](unsigned char c) { return std::isspace(c) != 0; };
  while (!value.empty() && is_space(static_cast<unsigned char>(value.front()))) {
    value.remove_prefix(1);
  }
  while (!value.empty() && is_space(static_cast<unsigned char>(value.back()))) {
    value.remove_suffix(1);
  }
  return std::string(value);
}

[[nodiscard]] std::string lower(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return value;
}

[[nodiscard]] std::vector<std::string> split_list(const std::string& value) {
  std::vector<std::string> items;
  std::stringstream stream(value);
  std::string item;
  while (std::getline(stream, item, ',')) {
    const std::string trimmed = trim(item);
    if (!trimmed.empty()) {
      items.push_back(trimmed);
    }
  }
  return items;
}

[[nodiscard]] double parse_double(const std::string& key, const std::string& value) {
  try {
    std::size_t consumed = 0;
    const double parsed = std::stod(value, &consumed);
    if (consumed != value.size()) {
      throw std::invalid_argument("trailing characters");
    }
    return parsed;
  } catch (const std::exception&) {
    throw std::runtime_error("invalid number for '" + key + "': " + value);
  }
}

[[nodiscard]] std::size_t parse_size(const std::string& key, const std::string& value) {
  try {
    std::size_t consumed = 0;
    const auto parsed = std::stoull(value, &consumed);
    if (consumed != value.size()) {
      throw std::invalid_argument("trailing characters");
    }
    return static_cast<std::size_t>(parsed);
  } catch (const std::exception&) {
    throw std::runtime_error("invalid integer for '" + key + "': " + value);
  }
}

constexpr std::string_view kUsage =
    "volpulse-ingestion — VolPulse C++ ingestion & normalisation engine\n"
    "\n"
    "Usage: volpulse-ingestion [options]\n"
    "\n"
    "  --config <path>            Flat `key = value` configuration file\n"
    "  --symbols <A,B>            Underlying symbols to poll\n"
    "  --binary-log <path>        Binary audit log path\n"
    "  --replay <path>            Replay quotes from a flat NDJSON file\n"
    "  --max-batch <n>            Quotes per poll (default 512)\n"
    "  --poll-interval <seconds>  Idle poll interval (default 1.0)\n"
    "  --dry-run / --no-dry-run   Write to the audit log or not (default: on)\n"
    "  --help                     Show this message\n";

}  // namespace

void IngestionConfig::apply(const std::string& key, const std::string& raw_value) {
  const std::string name = lower(trim(key));
  const std::string value = trim(raw_value);

  if (name == "symbols") {
    symbols = split_list(value);
  } else if (name == "binary_log" || name == "binary_log_path") {
    binary_log_path = value;
  } else if (name == "replay" || name == "replay_source") {
    replay_source = value;
  } else if (name == "max_batch") {
    max_batch = parse_size(name, value);
  } else if (name == "poll_interval" || name == "poll_interval_seconds") {
    poll_interval_seconds = parse_double(name, value);
  } else if (name == "dry_run") {
    dry_run = lower(value) == "true" || value == "1" || lower(value) == "yes";
  } else if (name.empty() || name.front() == '#') {
    return;
  } else {
    throw std::runtime_error("unknown configuration key: " + name);
  }
}

IngestionConfig IngestionConfig::from_file(const std::filesystem::path& path) {
  std::ifstream stream(path);
  if (!stream) {
    throw std::runtime_error("cannot open configuration file: " + path.string());
  }

  IngestionConfig config;
  std::string line;
  while (std::getline(stream, line)) {
    const std::string trimmed = trim(line);
    if (trimmed.empty() || trimmed.front() == '#') {
      continue;
    }
    const auto separator = trimmed.find('=');
    if (separator == std::string::npos) {
      throw std::runtime_error("malformed configuration line (expected key = value): " + trimmed);
    }
    config.apply(trimmed.substr(0, separator), trimmed.substr(separator + 1));
  }
  return config;
}

IngestionConfig IngestionConfig::from_args(int argc, char** argv) {
  IngestionConfig config;
  std::filesystem::path config_file;

  const auto require_value = [&](int& index, const std::string& flag) -> std::string {
    if (index + 1 >= argc) {
      throw std::runtime_error("missing value for " + flag);
    }
    ++index;
    return std::string(argv[index]);
  };

  for (int index = 1; index < argc; ++index) {
    const std::string argument(argv[index]);
    if (argument == "--help" || argument == "-h") {
      std::cout << kUsage;
      std::exit(0);
    } else if (argument == "--config") {
      config_file = require_value(index, argument);
    } else if (argument == "--symbols") {
      config.symbols = split_list(require_value(index, argument));
    } else if (argument == "--binary-log") {
      config.binary_log_path = require_value(index, argument);
    } else if (argument == "--replay") {
      config.replay_source = require_value(index, argument);
    } else if (argument == "--max-batch") {
      config.max_batch = parse_size("max_batch", require_value(index, argument));
    } else if (argument == "--poll-interval") {
      config.poll_interval_seconds = parse_double("poll_interval", require_value(index, argument));
    } else if (argument == "--dry-run") {
      config.dry_run = true;
    } else if (argument == "--no-dry-run") {
      config.dry_run = false;
    } else {
      throw std::runtime_error("unknown argument: " + argument);
    }
  }

  if (!config_file.empty()) {
    const IngestionConfig from_file_config = IngestionConfig::from_file(config_file);
    // Command line flags were applied first, so re-apply them over the file.
    if (config.symbols.empty()) {
      config.symbols = from_file_config.symbols;
    }
    if (config.replay_source.empty()) {
      config.replay_source = from_file_config.replay_source;
    }
    if (config.binary_log_path == IngestionConfig{}.binary_log_path) {
      config.binary_log_path = from_file_config.binary_log_path;
    }
    config.max_batch = from_file_config.max_batch;
    config.poll_interval_seconds = from_file_config.poll_interval_seconds;
    config.dry_run = from_file_config.dry_run;
  }

  return config;
}

void IngestionConfig::validate() const {
  if (max_batch == 0) {
    throw std::runtime_error("max_batch must be greater than zero");
  }
  if (poll_interval_seconds <= 0.0) {
    throw std::runtime_error("poll_interval_seconds must be greater than zero");
  }
  if (replay_source.empty() && symbols.empty()) {
    throw std::runtime_error(
        "no work configured: provide --symbols for live polling or --replay for replay");
  }
}

std::string IngestionConfig::describe() const {
  std::ostringstream out;
  out << "symbols=[";
  for (std::size_t index = 0; index < symbols.size(); ++index) {
    out << (index == 0 ? "" : ",") << symbols[index];
  }
  out << "] binary_log=" << binary_log_path.string() << " replay="
      << (replay_source.empty() ? "<live>" : replay_source.string())
      << " max_batch=" << max_batch << " poll_interval=" << poll_interval_seconds
      << " dry_run=" << (dry_run ? "true" : "false");
  return out.str();
}

}  // namespace volpulse::ingestion
