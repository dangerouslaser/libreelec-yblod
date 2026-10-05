cmake_minimum_required(VERSION 3.20)
project(YblodNativeCompatibility LANGUAGES C)

# Historical entry point. The authoritative native source/build is engine/.
include(CTest)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../../../engine"
                 "${CMAKE_CURRENT_BINARY_DIR}/engine")
