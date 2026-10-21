// ─────────────────────────────────────────────────────────────────────────────
// Memory-mapped append-only binary log writer.
// ─────────────────────────────────────────────────────────────────────────────
#include "volpulse/binarylog/writer.h"

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

[[nodiscard]] std::size_t page_size() noexcept {
  const long size = ::sysconf(_SC_PAGESIZE);
  return size > 0 ? static_cast<std::size_t>(size) : 4096U;
}

}  // namespace

MappedWriter::MappedWriter(const std::filesystem::path& path, std::size_t initial_capacity)
    : path_(path) {
  fd_ = ::open(path_.c_str(), O_RDWR | O_CREAT | O_CLOEXEC, 0644);
  if (fd_ < 0) {
    throw system_error("open " + path_.string());
  }

  try {
    struct stat status{};
    if (::fstat(fd_, &status) != 0) {
      throw system_error("fstat " + path_.string());
    }

    const auto file_size = static_cast<std::size_t>(status.st_size);
    if (file_size > 0) {
      // Recover the extent of the valid record sequence before appending.
      void* existing = ::mmap(nullptr, file_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, 0);
      if (existing == MAP_FAILED) {
        throw system_error("mmap " + path_.string());
      }
      const auto* bytes = static_cast<const std::byte*>(existing);
      const ScanResult scan = scan_records(std::span<const std::byte>(bytes, file_size));
      ::munmap(existing, file_size);

      end_offset_ = scan.valid_end;
      next_sequence_ = (scan.record_count == 0) ? 0U : scan.last_sequence + 1U;

      if (scan.valid_end != file_size) {
        // A torn tail from a previous crash: drop it rather than appending
        // after garbage, which would make the whole tail unreadable.
        if (::ftruncate(fd_, static_cast<off_t>(scan.valid_end)) != 0) {
          throw system_error("ftruncate " + path_.string());
        }
      }
    }

    map_window(initial_capacity);
  } catch (...) {
    close_window();
    if (fd_ >= 0) {
      ::close(fd_);
      fd_ = -1;
    }
    throw;
  }
}

MappedWriter::~MappedWriter() {
  close_file();
}

MappedWriter::MappedWriter(MappedWriter&& other) noexcept
    : path_(std::move(other.path_)),
      fd_(std::exchange(other.fd_, -1)),
      mapping_(std::exchange(other.mapping_, nullptr)),
      capacity_(std::exchange(other.capacity_, 0)),
      end_offset_(std::exchange(other.end_offset_, 0)),
      next_sequence_(std::exchange(other.next_sequence_, 0)) {}

MappedWriter& MappedWriter::operator=(MappedWriter&& other) noexcept {
  if (this != &other) {
    close_file();
    path_ = std::move(other.path_);
    fd_ = std::exchange(other.fd_, -1);
    mapping_ = std::exchange(other.mapping_, nullptr);
    capacity_ = std::exchange(other.capacity_, 0);
    end_offset_ = std::exchange(other.end_offset_, 0);
    next_sequence_ = std::exchange(other.next_sequence_, 0);
  }
  return *this;
}

void MappedWriter::map_window(std::size_t capacity) {
  const std::size_t page = page_size();
  std::size_t required = capacity;
  if (end_offset_ > 0) {
    const std::size_t needed = ((end_offset_ + page - 1U) / page) * page;
    if (needed > required) {
      required = needed;
    }
  }

  if (::ftruncate(fd_, static_cast<off_t>(required)) != 0) {
    throw system_error("ftruncate " + path_.string());
  }

  void* address = ::mmap(nullptr, required, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, 0);
  if (address == MAP_FAILED) {
    throw system_error("mmap " + path_.string());
  }

  mapping_ = address;
  capacity_ = required;
}

void MappedWriter::close_window() noexcept {
  if (mapping_ != nullptr) {
    ::munmap(mapping_, capacity_);
    mapping_ = nullptr;
  }
  capacity_ = 0;
}

void MappedWriter::close_file() noexcept {
  close_window();
  if (fd_ >= 0) {
    // Trim the file to its logical size so the on-disk artefact matches the
    // data written, rather than the size of the reserved mapping window.
    if (end_offset_ > 0) {
      (void)::ftruncate(fd_, static_cast<off_t>(end_offset_));
    }
    ::close(fd_);
    fd_ = -1;
  }
}

void MappedWriter::grow_to(std::size_t required) {
  std::size_t target = (capacity_ == 0) ? kDefaultMapCapacity : capacity_;
  while (target < required) {
    target *= 2U;
  }
  close_window();
  map_window(target);
}

std::uint64_t MappedWriter::append(std::span<const std::byte> payload, std::int64_t timestamp_ns) {
  const std::size_t padded = align_up(payload.size(), kPayloadAlignment);
  const std::size_t required = kRecordHeaderSize + padded;

  if (end_offset_ + required > capacity_) {
    grow_to(end_offset_ + required);
  }

  auto* base = static_cast<std::byte*>(mapping_);
  const std::size_t record_offset = end_offset_;

  RecordHeader header{};
  header.magic = kRecordMagic;
  header.version = kFormatVersion;
  header.flags = static_cast<std::uint16_t>(RecordFlags::kNone);
  header.payload_size = static_cast<std::uint32_t>(payload.size());
  header.sequence = next_sequence_;
  header.timestamp_ns = timestamp_ns;
  header.crc32 = crc32_ieee(payload);

  std::memcpy(base + record_offset, &header, kRecordHeaderSize);
  if (!payload.empty()) {
    std::memcpy(base + record_offset + kRecordHeaderSize, payload.data(), payload.size());
  }
  if (padded > payload.size()) {
    std::memset(base + record_offset + kRecordHeaderSize + payload.size(), 0,
                padded - payload.size());
  }

  end_offset_ += required;
  ++next_sequence_;

  return static_cast<std::uint64_t>(record_offset);
}

std::uint64_t MappedWriter::append(std::string_view text, std::int64_t timestamp_ns) {
  const auto* bytes = reinterpret_cast<const std::byte*>(text.data());
  return append(std::span<const std::byte>(bytes, text.size()), timestamp_ns);
}

void MappedWriter::flush() {
  if (mapping_ != nullptr && capacity_ > 0) {
    ::msync(mapping_, capacity_, MS_SYNC);
  }
}

void MappedWriter::sync() {
  flush();
  if (fd_ >= 0) {
    ::fsync(fd_);
  }
}

}  // namespace volpulse::binarylog
