#!/bin/sh
# Run inside an externally memory/CPU-limited LibreELEC SDK container.
set -eu
out=${1:?usage: build_libplacebo_diagnostics.sh NEW_OUTPUT_DIRECTORY}
cc=${YB_SDK_CC:-/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain/bin/x86_64-libreelec-linux-gnu-gcc}
engine=$(CDPATH= cd -- "$(dirname "$0")/../../../engine" && pwd)
mkdir "$out"
compile_probe() {
  source=$1
  backend=$2
  name=$3
  "$cc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow \
    -I"$engine/experimental" -I"$engine/include" \
    "$engine/experimental/$source" "$engine/experimental/$backend" \
    "$engine/experimental/native_gpu_guard.c" "$engine/experimental/native_scaled_surface.c" \
    "$engine/experimental/native_decoder_frame_bridge.c" "$engine/experimental/native_mmr_composer.c" \
    "$engine/experimental/native_integration_probe.c" "$engine/experimental/native_sampling_probe.c" \
    "$engine/src/native_composer.c" -lEGL -lm -o "$out/$name"
}
compile_probe native_gpu_composer_compare_probe.c native_gpu_composer_backend.c compare-probe
compile_probe native_gpu_composer_compare_probe.c native_gpu_composer_backend_libplacebo.c uniform-probe
compile_probe native_gpu_composer_sequence_probe.c native_gpu_composer_backend_libplacebo.c sequence-probe
"$cc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow \
  "$engine/experimental/native_libplacebo_reshape_generate.c" -lplacebo -lm -o "$out/reshape-generate"
"$cc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow \
  -DYB_GPU_BACKEND_HOST_ONLY -I"$engine/experimental" -I"$engine/include" \
  "$engine/experimental/native_gpu_metadata_export.c" "$engine/experimental/native_gpu_composer_backend.c" \
  "$engine/experimental/native_gpu_guard.c" "$engine/src/native_composer.c" -lm -o "$out/metadata-export"
"$cc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow \
  -I"$engine/experimental" -I"$engine/include" "$engine/experimental/native_libplacebo_precision_fixture.c" \
  "$engine/experimental/native_gpu_guard.c" "$engine/src/native_composer.c" -lm -o "$out/precision-fixture"
