# ─────────────────────────────────────────────────────────────────────────────
# VolPulse — C++ workspace root.
#
# Layout:
#   libs/cpp-core        shared C++ libraries (binary log, http, kafka, util)
#   services/ingestion-cpp   the C++ ingestion & normalisation service
#
# Targets are namespaced `volpulse::*` so they never collide with system
# libraries, and every public header lives under include/volpulse/.
# ─────────────────────────────────────────────────────────────────────────────
cmake_minimum_required(VERSION 3.24)

project(volpulse
  VERSION 0.1.0
  DESCRIPTION "VolPulse C++ ingestion & normalisation engine"
  LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "" FORCE)
endif()

option(VOLPULSE_BUILD_TESTS "Build unit tests" ON)
option(VOLPULSE_ENABLE_ASAN "Enable AddressSanitizer + UBSan" OFF)
option(VOLPULSE_ENABLE_TSAN "Enable ThreadSanitizer" OFF)
option(VOLPULSE_ENABLE_LTO "Enable link-time optimisation" OFF)

# ── Warnings: errors in CI, advisory locally ──────────────────────────────
add_library(volpulse_warnings INTERFACE)
if(MSVC)
  target_compile_options(volpulse_warnings INTERFACE /W4 /WX /permissive-)
else()
  target_compile_options(volpulse_warnings INTERFACE
    -Wall -Wextra -Wpedantic
    -Wshadow -Wconversion -Wsign-conversion
    -Wnon-virtual-dtor -Wold-style-cast -Woverloaded-virtual
    -Wdouble-promotion -Wnull-dereference
  )
endif()

# ── Sanitizers ─────────────────────────────────────────────────────────────
if(VOLPULSE_ENABLE_ASAN)
  add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address,undefined)
endif()
if(VOLPULSE_ENABLE_TSAN)
  add_compile_options(-fsanitize=thread -fno-omit-frame-pointer)
  add_link_options(-fsanitize=thread)
endif()

# ── Release tuning: the ingestion path is latency sensitive ───────────────
if(CMAKE_BUILD_TYPE STREQUAL "Release" OR VOLPULSE_ENABLE_LTO)
  set(CMAKE_INTERPROCEDURAL_OPTIMIZATION ON)
endif()

# ── Third-party dependencies ───────────────────────────────────────────────
# Protobuf and gRPC are consumed through vcpkg (see vcpkg.json). The manifest
# is the single declaration of the C++ dependency set.
find_package(Protobuf CONFIG QUIET)
find_package(gRPC CONFIG QUIET)
if(NOT Protobuf_FOUND OR NOT gRPC_FOUND)
  message(STATUS
    "volpulse: protobuf/gRPC not found by find_package. "
    "Install them via vcpkg (vcpkg.json) or set CMAKE_TOOLCHAIN_FILE.")
endif()

find_package(Threads REQUIRED)

# ── Testing ───────────────────────────────────────────────────────────────
# enable_testing() must be called from the top level so that ctest finds the
# tests registered in the subdirectories.
if(VOLPULSE_BUILD_TESTS)
  enable_testing()
endif()

# ── Warnings-as-errors in CI ───────────────────────────────────────────────
if(DEFINED ENV{CI} AND NOT "$ENV{CI}" STREQUAL "")
  target_compile_options(volpulse_warnings INTERFACE -Werror)
endif()

add_subdirectory(libs/cpp-core)
add_subdirectory(services/ingestion-cpp)

message(STATUS "volpulse: build type      = ${CMAKE_BUILD_TYPE}")
message(STATUS "volpulse: tests           = ${VOLPULSE_BUILD_TESTS}")
message(STATUS "volpulse: sanitizers      = asan=${VOLPULSE_ENABLE_ASAN} tsan=${VOLPULSE_ENABLE_TSAN}")
