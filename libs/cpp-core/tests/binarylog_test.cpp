// ─────────────────────────────────────────────────────────────────────────────
// Unit tests for the binary audit log.
//
// The suite is self-contained on purpose: it must be runnable on a machine
// with nothing but a C++20 compiler, so it uses a tiny assertion harness
// instead of a test framework dependency.
// ─────────────────────────────────────────────────────────────────────────────
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "volpulse/binarylog/reader.h"
#include "volpulse/binarylog/writer.h"

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool condition, const char* expression, const char* file, int line) {
  ++g_checks;
  if (!condition) {
    ++g_failures;
    std::fprintf(stderr, "FAIL %s:%d: %s\n", file, line, expression);
  }
}

#define CHECK(expr) check((expr), #expr, __FILE__, __LINE__)

std::filesystem::path temp_dir() {
  const auto path = std::filesystem::temp_directory_path() / "volpulse-binarylog-test";
  std::filesystem::remove_all(path);
  std::filesystem::create_directories(path);
  return path;
}

std::string payload_text(const std::vector<volpulse::binarylog::RecordView>& records,
                         std::size_t index) {
  const auto& payload = records[index].payload;
  return std::string(reinterpret_cast<const char*>(payload.data()), payload.size());
}

void test_round_trip() {
  const auto dir = temp_dir();
  const auto path = dir / "quotes.vlog";

  const std::vector<std::string> payloads = {
    "first payload",
    "second payload with a slightly longer body to exercise the alignment path",
    "x",
    "",
  };

  {
    volpulse::binarylog::MappedWriter writer(path, 4096);
    for (std::size_t index = 0; index < payloads.size(); ++index) {
      const auto offset = writer.append(
        payloads[index], 1'700'000'000'000'000'000LL + static_cast<std::int64_t>(index));
      CHECK(offset > 0 || index == 0);
    }
    writer.sync();
  }

  volpulse::binarylog::MappedReader reader(path);
  CHECK(reader.records().size() == payloads.size());
  CHECK(!reader.has_truncated_tail());

  std::string error;
  CHECK(reader.verify(error));

  for (std::size_t index = 0; index < payloads.size() && index < reader.records().size(); ++index) {
    CHECK(payload_text(reader.records(), index) == payloads[index]);
    CHECK(reader.records()[index].header.sequence == index);
  }

  std::filesystem::remove_all(dir);
}

void test_appends_after_existing_records() {
  const auto dir = temp_dir();
  const auto path = dir / "resume.vlog";

  {
    volpulse::binarylog::MappedWriter writer(path, 4096);
    (void)writer.append("alpha", 1);
    (void)writer.append("beta", 2);
    writer.sync();
  }

  {
    volpulse::binarylog::MappedWriter writer(path, 4096);
    CHECK(writer.sequence() == 2);
    CHECK(writer.size() > 0);
    (void)writer.append("gamma", 3);
    writer.sync();
  }

  volpulse::binarylog::MappedReader reader(path);
  CHECK(reader.records().size() == 3);
  CHECK(payload_text(reader.records(), 2) == "gamma");
  CHECK(reader.records()[2].header.sequence == 2);

  std::filesystem::remove_all(dir);
}

void test_truncated_tail_is_healed() {
  const auto dir = temp_dir();
  const auto path = dir / "torn.vlog";

  {
    volpulse::binarylog::MappedWriter writer(path, 4096);
    (void)writer.append("intact", 1);
    writer.sync();
  }

  // Append garbage, simulating a crash in the middle of a record.
  {
    std::ofstream stream(path, std::ios::app | std::ios::binary);
    const char garbage[16] = {'\x01', '\x02', '\x03', '\x04', '\x05', '\x06', '\x07', '\x08',
                              '\x09', '\x0a', '\x0b', '\x0c', '\x0d', '\x0e', '\x0f', '\x10'};
    stream.write(garbage, sizeof(garbage));
  }

  {
    volpulse::binarylog::MappedWriter writer(path, 4096);
    CHECK(writer.sequence() == 1);
    (void)writer.append("after-heal", 2);
    writer.sync();
  }

  volpulse::binarylog::MappedReader reader(path);
  CHECK(reader.records().size() == 2);
  CHECK(payload_text(reader.records(), 0) == "intact");
  CHECK(payload_text(reader.records(), 1) == "after-heal");
  CHECK(!reader.has_truncated_tail());

  std::filesystem::remove_all(dir);
}

void test_corruption_is_detected() {
  const auto dir = temp_dir();
  const auto path = dir / "corrupt.vlog";

  {
    volpulse::binarylog::MappedWriter writer(path, 4096);
    (void)writer.append("payload-to-corrupt", 1);
    writer.sync();
  }

  // Flip a byte inside the payload region.
  {
    std::fstream stream(path, std::ios::in | std::ios::out | std::ios::binary);
    stream.seekp(40, std::ios::beg);
    const char corrupted = 'X';
    stream.write(&corrupted, 1);
  }

  volpulse::binarylog::MappedReader reader(path);
  std::string error;
  CHECK(!reader.verify(error));
  CHECK(!error.empty());

  std::filesystem::remove_all(dir);
}

void test_growth_beyond_initial_capacity() {
  const auto dir = temp_dir();
  const auto path = dir / "grow.vlog";

  const std::string filler(512, 'x');
  {
    volpulse::binarylog::MappedWriter writer(path, 1024);
    for (int index = 0; index < 64; ++index) {
      (void)writer.append(filler, index);
    }
    writer.sync();
  }

  volpulse::binarylog::MappedReader reader(path);
  CHECK(reader.records().size() == 64);
  CHECK(!reader.has_truncated_tail());

  std::filesystem::remove_all(dir);
}

void test_crc_known_vector() {
  // The IEEE 802.3 CRC-32 of "123456789" is 0xCBF43926.
  const std::string input = "123456789";
  const auto bytes =
    std::span<const std::byte>(reinterpret_cast<const std::byte*>(input.data()), input.size());
  CHECK(volpulse::binarylog::crc32_ieee(bytes) == 0xCBF43926U);
}

}  // namespace

int main() {
  test_crc_known_vector();
  test_round_trip();
  test_appends_after_existing_records();
  test_truncated_tail_is_healed();
  test_corruption_is_detected();
  test_growth_beyond_initial_capacity();

  std::printf("binarylog: %d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
