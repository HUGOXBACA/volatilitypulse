# `volpulse-cpp-core` — shared C++ libraries

The reusable half of the C++ stack: the binary audit log, the upstream HTTP
client, the broker transport and the small utilities they share. The
ingestion service in `services/ingestion-cpp` depends on this library; this
library never depends on the service.

## Layout

```
include/volpulse/
├── binarylog/
│   ├── format.h        The on-disk record format. The compatibility surface.
│   ├── writer.h        Memory-mapped append-only writer.
│   └── reader.h        Reader for replay and verification.
├── http/               The upstream REST/WebSocket client.
├── transport/          The broker producer.
└── util/               Time, error handling, small helpers.

src/                    The implementations.
tests/                  Unit tests, one binary per library.
```

## Design rules

* **The log format is frozen.** `RecordHeader` is a packed, fixed-width
  struct with a `static_assert` on its size and on the offset of its
  fields. Changing the layout is a breaking change that requires bumping
  `kFormatVersion` and shipping a migration.
* **Zero-copy on the hot path.** The writer maps the file and appends with a
  `memcpy`. There is no `write(2)` per record.
* **The writer heals itself.** A torn tail left by a crash is detected on
  the next open and truncated. A damaged log is an incident, not a warning,
  so the reader stops at the first failed CRC and reports it.
* **No exceptions on the happy path.** Errors are reported by return value
  or by a thrown `std::runtime_error` at a boundary that can handle it.
* **Warnings are errors in CI.** The `volpulse_warnings` target compiles
  with `-Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wsign-conversion
  -Wold-style-cast` and adds `-Werror` when `CI` is set.

## Building

```bash
bash tools/scripts/bootstrap_cpp.sh   # vcpkg dependencies
cmake --preset dev
cmake --build --preset dev
ctest --preset dev --output-on-failure
```

Presets: `dev` (RelWithDebInfo, tests on), `debug` (ASan + UBSan),
`release` (LTO, tests off).

## Adding a module

1. Public headers go in `include/volpulse/<module>/`.
2. Implementations go in `src/<module>/`.
3. Add the sources to `CMakeLists.txt` explicitly. No globbing: an
   unlisted source is a source that does not get built.
4. Add a test in `tests/` and register it with `add_test`.
5. No dependency outside the standard library, `volpulse_cpp_core` and the
   vcpkg manifest.
