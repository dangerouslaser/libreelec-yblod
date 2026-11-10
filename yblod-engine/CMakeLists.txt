cmake_minimum_required(VERSION 3.22)
project(NativeDV VERSION 0.1 LANGUAGES C)
include(CTest)

# YBLOD 0.4.0: the Vulkan engine (vk/, packages/graphics/yblod-engine-vk) is
# the only Dolby Vision engine. Its build.rs compiles the host C in src/
# directly; the OpenCL engine library (libdv_source_private) and its install
# rules are gone. What stays here are the host C's CPU contract tests.

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
add_compile_options(-Wall -Wextra -Wconversion -ffp-contract=off)

if(BUILD_TESTING)
  add_executable(polynomial_fel_tests tests/polynomial_fel_tests.c
    src/pixel_luma.c src/pixel_chroma_final.c src/mmr_prepare.c src/pixel_spatial.c)
  target_include_directories(polynomial_fel_tests PRIVATE src)
  target_compile_options(polynomial_fel_tests PRIVATE -UNDEBUG)
  add_test(NAME polynomial_fel COMMAND polynomial_fel_tests)
  foreach(pair "order2_gate;single_reshape" "source_geometry;source_geometry" "scanout_slots;dv_scanout_slots")
    list(GET pair 0 test_name)
    list(GET pair 1 implementation)
    add_executable(${test_name}_tests tests/${test_name}_tests.c src/${implementation}.c)
    target_include_directories(${test_name}_tests PRIVATE src)
    target_compile_options(${test_name}_tests PRIVATE -UNDEBUG)
    add_test(NAME ${test_name} COMMAND ${test_name}_tests)
  endforeach()
endif()
