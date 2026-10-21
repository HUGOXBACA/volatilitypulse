add_library(volpulse_ingestion_core STATIC
  src/config.cpp
  src/ndjson_source.cpp
  src/pipeline.cpp
  src/quote_codec.cpp
)

add_library(volpulse::ingestion_core ALIAS volpulse_ingestion_core)

target_include_directories(volpulse_ingestion_core
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

target_compile_features(volpulse_ingestion_core PUBLIC cxx_std_20)
target_link_libraries(volpulse_ingestion_core PUBLIC volpulse::cpp_core)

add_executable(volpulse-ingestion src/main.cpp)
target_link_libraries(volpulse-ingestion PRIVATE volpulse_ingestion_core)
set_target_properties(volpulse-ingestion PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

if(VOLPULSE_BUILD_TESTS)
  enable_testing()
  add_executable(volpulse_ingestion_test tests/pipeline_test.cpp)
  target_link_libraries(volpulse_ingestion_test PRIVATE volpulse_ingestion_core)
  add_test(NAME cpp.ingestion COMMAND volpulse_ingestion_test)

  add_executable(volpulse_benchmarks tests/benchmarks/run_benchmarks.cpp)
  target_link_libraries(volpulse_benchmarks PRIVATE volpulse_ingestion_core)
  set_target_properties(volpulse_benchmarks PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
  add_test(NAME cpp.benchmarks COMMAND volpulse_benchmarks)

  add_executable(volpulse_latency_benchmarks tests/benchmarks/latency_benchmarks.cpp)
  target_link_libraries(volpulse_latency_benchmarks PRIVATE volpulse_ingestion_core)
  set_target_properties(volpulse_latency_benchmarks PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
  add_test(NAME cpp.latency_benchmarks COMMAND volpulse_latency_benchmarks)
endif()
