cmake_minimum_required(VERSION 3.20)
project(YblodNative VERSION 0.1.0 LANGUAGES C)

# This builds only the tested native foundations, not a player or a Python
# adapter. Diagnostic probes and benchmarks deliberately remain outside it.
include(CheckCSourceCompiles)
check_c_source_compiles("int main(void) { __int128 v = 1; return (int)v; }"
                        YBLOD_HAS_INT128)
if(NOT YBLOD_HAS_INT128)
  message(FATAL_ERROR "YblodNative requires a compiler with signed __int128")
endif()
if(NOT CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
  message(FATAL_ERROR "Only GCC and Clang are currently validated")
endif()

include(GNUInstallDirs)
add_library(yblod_native STATIC native_composer.c native_colour.c native_y416.c)
target_compile_features(yblod_native PUBLIC c_std_11)
set_target_properties(yblod_native PROPERTIES POSITION_INDEPENDENT_CODE ON
  C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO
  INTERPROCEDURAL_OPTIMIZATION FALSE)
target_compile_options(yblod_native PRIVATE -Wall -Wextra -Werror -Wconversion -Wshadow)
set_source_files_properties(native_colour.c PROPERTIES
  COMPILE_OPTIONS "-fno-fast-math;-ffp-contract=off")
target_include_directories(yblod_native PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/yblod>)
if(UNIX)
  target_link_libraries(yblod_native PUBLIC m)
endif()

install(TARGETS yblod_native EXPORT YblodNativeTargets
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(FILES native_composer.h native_colour.h native_y416.h
  DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/yblod)
install(EXPORT YblodNativeTargets NAMESPACE Yblod::
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/YblodNative)

include(CMakePackageConfigHelpers)
configure_package_config_file(YblodNativeConfig.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/YblodNativeConfig.cmake
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/YblodNative)
write_basic_package_version_file(${CMAKE_CURRENT_BINARY_DIR}/YblodNativeConfigVersion.cmake
  VERSION ${PROJECT_VERSION} COMPATIBILITY SameMajorVersion)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/YblodNativeConfig.cmake
              ${CMAKE_CURRENT_BINARY_DIR}/YblodNativeConfigVersion.cmake
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/YblodNative)

include(CTest)
if(BUILD_TESTING)
  add_executable(native_library_smoke native_library_smoke.c)
  target_link_libraries(native_library_smoke PRIVATE yblod_native)
  add_test(NAME native_library_smoke COMMAND native_library_smoke)
endif()
