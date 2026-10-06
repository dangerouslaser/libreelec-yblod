#!/bin/sh
set -eu
trap 'printf "bounded CPU playback LUT gate resources:\n"; for resource in memory.peak memory.swap.peak memory.events; do if [ -r "/sys/fs/cgroup/$resource" ]; then printf "%s\n" "$resource"; sed -n "1,12p" "/sys/fs/cgroup/$resource"; fi; done' EXIT
sdk=/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain
cc=$sdk/bin/x86_64-libreelec-linux-gnu-gcc
exp=/engine-repo/engine/experimental
inc=/engine-repo/engine/include
mkdir -p /lab/bin /lab/objects
flags='-std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow -fno-fast-math -ffp-contract=off'
includes="-I/lab -I$exp -I$inc"
"$cc" $flags $includes /lab/test_native_gpu_nlq_lut.c /lab/native_gpu_nlq_lut.c /engine-repo/engine/src/native_composer.c -o /lab/bin/test-native-gpu-nlq-lut
"$cc" $flags $includes /lab/native_gpu_composer_fp32_compare_probe.c "$exp/native_gpu_composer_backend.c" /lab/native_gpu_composer_fp32_backend.c /lab/native_gpu_nlq_lut.c /lab/native_gpu_composer_fp32.c "$exp/native_libplacebo_reshape.c" "$exp/native_gpu_guard.c" "$exp/native_scaled_surface.c" "$exp/native_decoder_frame_bridge.c" "$exp/native_mmr_composer.c" "$exp/native_integration_probe.c" "$exp/native_sampling_probe.c" /engine-repo/engine/src/native_composer.c -o /lab/bin/fp32-playback-nlq-lut-compare-probe -lplacebo -lEGL -lm
for name in native_dovi_adapter native_dovi_colour_adapter native_playback_metadata native_gpu_guard native_gpu_composer_backend native_libplacebo_reshape native_gpu_preparation native_gpu_ycc_backend native_vaapi_el_scaler native_vaapi_gl_import native_egl_output_bridge; do
  "$cc" $flags $includes -c "$exp/$name.c" -o "/lab/objects/$name.o"
done
for name in native_gpu_composer_fp32 native_gpu_composer_fp32_backend native_gpu_nlq_lut native_playback_context; do
  "$cc" $flags $includes -c "/lab/$name.c" -o "/lab/objects/$name.o"
done
"$cc" $flags $includes /lab/test_nlq_lut_options.c /lab/objects/*.o /engine-repo/engine/src/native_composer.c /engine-repo/engine/src/native_colour.c -o /lab/bin/test-nlq-lut-options -lplacebo -lEGL -lva -lavutil -lm
libs=$sdk/x86_64-libreelec-linux-gnu/sysroot/usr/lib
"$libs/ld-linux-x86-64.so.2" --library-path "$libs" /lab/bin/test-native-gpu-nlq-lut "$exp/native_gpu_composer_backend.comp"
"$libs/ld-linux-x86-64.so.2" --library-path "$libs" /lab/bin/test-nlq-lut-options
