#!/bin/sh
# Tiny synthetic GPU check only; no movie, HDMI or performance qualification.
set -eu
: "${SDK_SYSROOT:?Set SDK_SYSROOT to the SDK sysroot}"
: "${PROBE_OUTPUT_DIR:?Set PROBE_OUTPUT_DIR to the probe binary directory}"
: "${LIBGL_DRIVERS_PATH:?Set LIBGL_DRIVERS_PATH to the matching Mesa DRI directory}"
test "$(sed -n '1p' /sys/fs/cgroup/memory.max)" = 536870912
test "$(sed -n '1p' /sys/fs/cgroup/memory.swap.max)" = 0
awk '{exit !($1 != "max" && $1 > 0 && $2 > 0 && $1 <= $2)}' /sys/fs/cgroup/cpu.max
task_reference=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_root=$(CDPATH= cd -- "$task_reference/../../.." && pwd)
export LIBGL_DRIVERS_PATH
__EGL_VENDOR_LIBRARY_FILENAMES="$SDK_SYSROOT/usr/share/glvnd/egl_vendor.d/50_mesa.json" \
 "$SDK_SYSROOT/usr/lib/ld-linux-x86-64.so.2" --library-path "$SDK_SYSROOT/usr/lib" \
 "$PROBE_OUTPUT_DIR/native_gpu_instruction_gpu_probe" /dev/dri/renderD128 \
 "$task_root/engine/experimental/native_gpu_composer_backend.comp"
for task_field in memory.max memory.swap.max cpu.max memory.peak memory.events memory.swap.current; do
 printf '%s: ' "$task_field"; sed -n '1,20p' "/sys/fs/cgroup/$task_field"
done
