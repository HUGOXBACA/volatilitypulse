// ─────────────────────────────────────────────────────────────────────────────
// Memory-mapped reader for the binary audit log.
// ─────────────────────────────────────────────────────────────────────────────
#include "volpulse/binarylog/reader.h"

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <stdexcept>
#include <string>
#include <utility>

namespace volpulse::binarylog {
namespace {

[[nodiscard]] std::runtime_error system_error(const std::string& what) {
  return std::runtime_error(what + ": " + std::strerror(errno));
}

}  // namespace

MappedReader::MappedReader(const std::filesystem::path& path) : path_(path) {
  fd_ = ::open(path_.c_str(), O_RDONLY | O_CLOEXEC);
  if (fd_ < 0) {
    throw system_error("open " + path_.string());
  }

  try {
    struct stat status{};
    if (::fstat(fd_, &status) != 0) {
      throw system_error("fstat " + path_.string());
    }

    mapped_size_ = static_cast<std::size_t>(status.st_size);
    if (mapped_size_ == 0) {
      return;
    }

    void* address = ::mmap(nullptr, mapped_size_, PROT_READ, MAP_SHARED, fd_, 0);
    if (address == MAP_FAILED) {
      throw system_error("mmap " + path_.string());
    }
    mapping_ = address;

    const auto* bytes = static_cast<const std::byte*>(mapping_);
    scan_ = scan_records(std::span<const std::byte>(bytes, mapped_size_));

    std::size_t offset = 0;
    records_.reserve(static_cast<std::size_t>(scan_.record_count));
    while (offset + kRecordHeaderSize <= scan_.valid_end) {
      RecordHeader header{};
      std::memcpy(&header, bytes + offset, kRecordHeaderSize);
      const std::size_t padded =
        align_up(static_cast<std::size_t>(header.payload_size), kPayloadAlignment);
      const auto* payload = bytes + offset + kRecordHeaderSize;
      records_.push_back(RecordView{
        header,
        std::span<const std::byte>(payload, static_cast<std::size_t>(header.payload_size)),
      });
      offset += kRecordHeaderSize + padded;
    }
  } catch (...) {
    close_window();
    if (fd_ >= 0) {
      ::close(fd_);
      fd_ = -1;
    }
    throw;
  }
}

MappedReader::~MappedReader() {
  close_window();
  if (fd_ >= 0) {
    ::close(fd_);
    fd_ = -1;
  }
}

MappedReader::MappedReader(MappedReader&& other) noexcept
    : path_(std::move(other.path_)),
      fd_(std::exchange(other.fd_, -1)),
      mapping_(std::exchange(other.mapping_, nullptr)),
      mapped_size_(std::exchange(other.mapped_size_, 0)),
      records_(std::move(other.records_)),
      scan_(other.scan_) {
  other.scan_ = ScanResult{};
}

MappedReader& MappedReader::operator=(MappedReader&& other) noexcept {
  if (this != &other) {
    close_window();
    if (fd_ >= 0) {
      ::close(fd_);
    }
    path_ = std::move(other.path_);
    fd_ = std::exchange(other.fd_, -1);
    mapping_ = std::exchange(other.mapping_, nullptr);
    mapped_size_ = std::exchange(other.mapped_size_, 0);
    records_ = std::move(other.records_);
    scan_ = other.scan_;
    other.scan_ = ScanResult{};
  }
  return *this;
}

void MappedReader::close_window() noexcept {
  if (mapping_ != nullptr) {
    ::munmap(mapping_, mapped_size_);
    mapping_ = nullptr;
  }
  mapped_size_ = 0;
}

bool MappedReader::verify(std::string& error) const {
  for (std::size_t index = 0; index < records_.size(); ++index) {
    const RecordView& record = records_[index];
    if (record.header.magic != kRecordMagic) {
      error = "record " + std::to_string(index) + ": bad magic";
      return false;
    }
    if (record.header.version != kFormatVersion) {
      error = "record " + std::to_string(index) + ": unsupported format version";
      return false;
    }
    if (crc32_ieee(record.payload) != record.header.crc32) {
      error = "record " + std::to_string(index) + ": CRC mismatch";
      return false;
    }
  }
  if (scan_.truncated_tail) {
    error = "log has a truncated or corrupt tail after " + std::to_string(scan_.record_count) +
            " valid records";
    return false;
  }
  return true;
}

}  // namespace volpulse::binarylog
