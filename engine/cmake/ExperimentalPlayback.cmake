# Explicit opt-in integration library; Kodi integration remains external.
# Integer composer is default; DVBRIDGE_NATIVE_FP32=1 selects experimental hybrid.
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "Experimental playback currently requires Linux VAAPI/EGL")
endif()
find_package(PkgConfig REQUIRED)
pkg_check_modules(YbNativeAvutil REQUIRED IMPORTED_TARGET libavutil>=59.12.100)
string(REGEX MATCH "^[0-9]+" YBLOD_AVUTIL_ABI_MAJOR "${YbNativeAvutil_VERSION}")
if(NOT YBLOD_AVUTIL_ABI_MAJOR)
  message(FATAL_ERROR "Cannot determine build-time libavutil ABI major")
endif()
math(EXPR YBLOD_AVUTIL_ABI_NEXT "${YBLOD_AVUTIL_ABI_MAJOR} + 1")
pkg_check_modules(YbNativeEgl REQUIRED IMPORTED_TARGET egl)
pkg_check_modules(YbNativeVa REQUIRED IMPORTED_TARGET libva)
pkg_check_modules(YbNativePlacebo REQUIRED IMPORTED_TARGET libplacebo)
set(YB_NATIVE_PLAYBACK_SOURCES
  experimental/native_dovi_adapter.c
  experimental/native_dovi_colour_adapter.c
  experimental/native_playback_metadata.c
  experimental/native_gpu_guard.c
  experimental/native_gpu_composer_backend.c
  experimental/native_gpu_composer_fp32.c
  experimental/native_gpu_composer_fp32_backend.c
  experimental/native_gpu_nlq_lut.c
  experimental/native_libplacebo_reshape.c
  experimental/native_gpu_preparation.c
  experimental/native_gpu_ycc_backend.c
  experimental/native_vaapi_el_scaler.c
  experimental/native_vaapi_gl_import.c
  experimental/native_egl_output_bridge.c
  experimental/native_playback_context.c)
add_library(yblod_playback_native STATIC ${YB_NATIVE_PLAYBACK_SOURCES})
target_compile_features(yblod_playback_native PUBLIC c_std_11)
set_target_properties(yblod_playback_native PROPERTIES POSITION_INDEPENDENT_CODE ON
  C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO
  INTERPROCEDURAL_OPTIMIZATION FALSE)
target_compile_options(yblod_playback_native PRIVATE -fno-lto -Wall -Wextra -Werror
  -Wconversion -Wshadow -fno-fast-math -ffp-contract=off)
target_include_directories(yblod_playback_native PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/experimental>
  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/yblod>)
target_link_libraries(yblod_playback_native PUBLIC yblod_native
  PkgConfig::YbNativeAvutil PkgConfig::YbNativeEgl PkgConfig::YbNativeVa
  PkgConfig::YbNativePlacebo m)
install(TARGETS yblod_playback_native EXPORT YblodNativeTargets
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(FILES
  experimental/native_dovi_adapter.h experimental/native_dovi_colour_adapter.h
  experimental/native_playback_metadata.h experimental/native_gpu_guard.h
  experimental/native_gpu_composer_backend.h experimental/native_gpu_preparation.h
  experimental/native_gpu_ycc_backend.h experimental/native_vaapi_el_scaler.h
  experimental/native_vaapi_gl_import.h experimental/native_egl_output_bridge.h
  experimental/native_playback_context.h experimental/native_gpu_composer_fp32.h
  experimental/native_libplacebo_reshape.h
  experimental/native_gpu_nlq_lut.h
  DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/yblod)
install(FILES experimental/native_gpu_preparation_probe.comp
  experimental/native_gpu_composer_backend.comp experimental/native_gpu_reconstructed_ycc.comp
  DESTINATION ${CMAKE_INSTALL_DATADIR}/yblod/shaders)
