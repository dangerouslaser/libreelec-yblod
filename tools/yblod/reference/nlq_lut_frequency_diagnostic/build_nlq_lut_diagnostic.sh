#!/bin/sh
set -eu
trap 'printf "bounded CPU NLQ diagnostic compile/test cgroup:\\n"; for resource in memory.peak memory.swap.peak memory.events; do if [ -r "/sys/fs/cgroup/$resource" ]; then printf "%s\\n" "$resource"; sed -n "1,12p" "/sys/fs/cgroup/$resource"; fi; done' EXIT
sdk=/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain
cc=$sdk/bin/x86_64-libreelec-linux-gnu-gcc
exp=/engine-repo/engine/experimental
inc=/engine-repo/engine/include
mkdir -p /lab/bin
flags='-std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow -fno-fast-math -ffp-contract=off'
"$cc" $flags -I/lab -I"$exp" -I"$inc" /lab/test_native_gpu_diag_nlq_lut.c /lab/native_gpu_diag_nlq_lut.c /engine-repo/engine/src/native_composer.c -o /lab/bin/test-native-gpu-diag-nlq-lut
"$cc" $flags -I/lab -I"$exp" -I"$inc" /lab/native_gpu_composer_fp32_compare_probe.c "$exp/native_gpu_composer_backend.c" /lab/native_gpu_composer_fp32_backend.c /lab/native_gpu_diag_nlq_lut.c /lab/native_gpu_composer_fp32.c "$exp/native_libplacebo_reshape.c" "$exp/native_gpu_guard.c" "$exp/native_scaled_surface.c" "$exp/native_decoder_frame_bridge.c" "$exp/native_mmr_composer.c" "$exp/native_integration_probe.c" "$exp/native_sampling_probe.c" /engine-repo/engine/src/native_composer.c -o /lab/bin/fp32-nlq-lut-compare-probe -lplacebo -lEGL -lm
libs=$sdk/x86_64-libreelec-linux-gnu/sysroot/usr/lib
"$libs/ld-linux-x86-64.so.2" --library-path "$libs" /lab/bin/test-native-gpu-diag-nlq-lut "$exp/native_gpu_composer_backend.comp"
