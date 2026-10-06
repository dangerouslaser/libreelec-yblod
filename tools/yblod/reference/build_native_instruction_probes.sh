#!/bin/sh
# Run inside a CPU1, 512MiB/no-swap, network-disabled SDK container.
set -eu
: "${SDK_CC:?Set SDK_CC to the SDK C compiler}"
: "${SDK_SYSROOT:?Set SDK_SYSROOT to the SDK sysroot}"
: "${SDK_NATIVE_LIBRARY_DIR:?Set SDK_NATIVE_LIBRARY_DIR to the existing native static-library directory}"
: "${PROBE_OUTPUT_DIR:?Set PROBE_OUTPUT_DIR to a dedicated writable output directory}"
test "$(sed -n '1p' /sys/fs/cgroup/memory.max)" = 536870912
test "$(sed -n '1p' /sys/fs/cgroup/memory.swap.max)" = 0
awk '{exit !($1 != "max" && $1 > 0 && $2 > 0 && $1 <= $2)}' /sys/fs/cgroup/cpu.max
task_reference=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_root=$(CDPATH= cd -- "$task_reference/../../.." && pwd)
task_engine="$task_root/engine/experimental"
test -d "$PROBE_OUTPUT_DIR"
for task_source in native_gpu_composer_fp32.c native_gpu_composer_fp32_backend.c; do
 "$SDK_CC" --sysroot="$SDK_SYSROOT" -std=c11 -O3 -fPIC -fno-lto -fno-fast-math -ffp-contract=off \
  -Wall -Wextra -Werror -Wconversion -Wshadow -I"$task_engine" -I"$task_root/engine/include" \
  -c "$task_engine/$task_source" -o "$PROBE_OUTPUT_DIR/$task_source.o"
done
"$SDK_CC" --sysroot="$SDK_SYSROOT" -std=c11 -O3 -UNDEBUG -fno-lto -fno-fast-math -ffp-contract=off \
 -Wall -Wextra -Werror -Wconversion -Wshadow -I"$task_engine" -I"$task_root/engine/include" \
 -ffunction-sections -fdata-sections -Wl,--gc-sections \
 "$task_reference/native_gpu_instruction_upload_probe.c" \
 "$SDK_NATIVE_LIBRARY_DIR/libyblod_playback_native.a" "$SDK_NATIVE_LIBRARY_DIR/libyblod_native.a" \
 -lm -o "$PROBE_OUTPUT_DIR/native_gpu_instruction_upload_probe"
"$SDK_CC" --sysroot="$SDK_SYSROOT" -D_GNU_SOURCE -std=c11 -O3 -fno-lto -fno-fast-math -ffp-contract=off \
 -Wall -Wextra -Werror -Wconversion -Wshadow -I"$task_engine" -I"$task_root/engine/include" \
 -ffunction-sections -fdata-sections -Wl,--gc-sections \
 "$task_reference/native_gpu_instruction_gpu_probe.c" \
 "$PROBE_OUTPUT_DIR/native_gpu_composer_fp32.c.o" "$PROBE_OUTPUT_DIR/native_gpu_composer_fp32_backend.c.o" \
 "$SDK_NATIVE_LIBRARY_DIR/libyblod_playback_native.a" "$SDK_NATIVE_LIBRARY_DIR/libyblod_native.a" \
 -lm -lEGL -lplacebo -o "$PROBE_OUTPUT_DIR/native_gpu_instruction_gpu_probe"
"$SDK_SYSROOT/usr/lib/ld-linux-x86-64.so.2" --library-path "$SDK_SYSROOT/usr/lib" \
 "$PROBE_OUTPUT_DIR/native_gpu_instruction_upload_probe"
for task_field in memory.peak memory.events memory.swap.current; do
 printf '%s: ' "$task_field"; sed -n '1,20p' "/sys/fs/cgroup/$task_field"
done
