add_library(volpulse_cpp_core STATIC
  src/binarylog/format.cpp
  src/binarylog/writer.cpp
  src/binarylog/reader.cpp
)

add_library(volpulse::cpp_core ALIAS volpulse_cpp_core)

target_include_directories(volpulse_cpp_core
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

target_compile_features(volpulse_cpp_core PUBLIC cxx_std_20)
target_link_libraries(volpulse_cpp_core PUBLIC volpulse_warnings Threads::Threads)

find_package(Protobuf CONFIG QUIET)
if(Protobuf_FOUND)
  target_link_libraries(volpulse_cpp_core PUBLIC protobuf::libprotobuf)
endif()

if(VOLPULSE_BUILD_TESTS)
  enable_testing()
  add_executable(volpulse_binarylog_test tests/binarylog_test.cpp)
  target_link_libraries(volpulse_binarylog_test PRIVATE volpulse_cpp_core)
  add_test(NAME cpp.binarylog COMMAND volpulse_binarylog_test)

  add_executable(volpulse_latency_test tests/latency_test.cpp)
  target_link_libraries(volpulse_latency_test PRIVATE volpulse_cpp_core)
  add_test(NAME cpp.latency COMMAND volpulse_latency_test)
endif()
