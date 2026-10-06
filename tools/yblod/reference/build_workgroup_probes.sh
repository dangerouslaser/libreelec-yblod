#!/bin/sh
set -eu
# SDK diagnostic only. Controller supplies resource limits externally.
engine=${1:?usage: build_workgroup_probes.sh ENGINE_DIRECTORY STAGING_DIRECTORY NEW_OUTPUT_DIRECTORY}
stage=${2:?}
out=${3:?}
cc=${YB_SDK_CC:-/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain/bin/x86_64-libreelec-linux-gnu-gcc}
# Refuse replacing an existing output directory or any previous binary.
mkdir "$out"
for geometry in 8x8 16x8 16x16; do
  x=${geometry%x*}
  y=${geometry#*x}
  "$cc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow \
    -DYB_WORKGROUP_X="$x" -DYB_WORKGROUP_Y="$y" \
    -I"$engine/experimental" -I"$engine/include" \
    "$stage/native_gpu_composer_compare_probe.c" \
    "$engine/experimental/native_gpu_composer_backend_libplacebo_workgroup.c" \
    "$engine/experimental/native_gpu_guard.c" "$engine/experimental/native_scaled_surface.c" \
    "$engine/experimental/native_decoder_frame_bridge.c" "$engine/experimental/native_mmr_composer.c" \
    "$engine/experimental/native_integration_probe.c" "$engine/experimental/native_sampling_probe.c" \
    "$engine/src/native_composer.c" -lEGL -lm -o "$out/uniform-probe-$geometry"
done
