#!/bin/sh
# SDK diagnostic only. Controller supplies bounded container/cgroup externally.
set -eu
engine=${1:?usage: build_fp32_wrapper_diagnostic.sh ENGINE_DIRECTORY STAGING_DIRECTORY NEW_OUTPUT_DIRECTORY}
stage=${2:?}
out=${3:?}
cc=${YB_SDK_CC:-/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain/bin/x86_64-libreelec-linux-gnu-gcc}
mkdir "$out"
# Do NOT add staging/mock to include search: its mock backend header
# is deliberately NOT the real ABI. Production headers must win this build.
for kind in compare sequence; do
"$cc" -std=c11 -D_POSIX_C_SOURCE=200809L -O2 -fno-lto \
  -Wall -Wextra -Werror -Wconversion -Wshadow \
  -I"$engine/experimental" -I"$engine/include" \
  "$stage/native_gpu_composer_fp32_${kind}_probe.c" \
  "$engine/experimental/native_gpu_composer_backend.c" \
  "$engine/experimental/native_gpu_composer_fp32_backend.c" \
  "$engine/experimental/native_gpu_composer_fp32.c" \
  "$engine/experimental/native_gpu_nlq_lut.c" \
  "$engine/experimental/native_libplacebo_reshape.c" \
  "$engine/experimental/native_gpu_guard.c" \
  "$engine/experimental/native_scaled_surface.c" \
  "$engine/experimental/native_decoder_frame_bridge.c" \
  "$engine/experimental/native_mmr_composer.c" \
  "$engine/experimental/native_integration_probe.c" \
  "$engine/experimental/native_sampling_probe.c" \
  "$engine/src/native_composer.c" -lplacebo -lEGL -lm -o "$out/fp32-wrapper-${kind}-probe"
done
