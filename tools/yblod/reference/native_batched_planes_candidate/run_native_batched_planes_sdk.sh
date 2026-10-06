#!/bin/sh
set -eu
task_lab=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_engine=${YB_ENGINE_EXPERIMENTAL:-/repo/engine/experimental}
task_tc=${YB_SDK_TOOLCHAIN:-/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain}
task_sr=$task_tc/x86_64-libreelec-linux-gnu/sysroot
test "$(sed -n '1p' /sys/fs/cgroup/memory.max)" = 536870912
test "$(sed -n '1p' /sys/fs/cgroup/memory.swap.max)" = 0
awk '{exit !($1 != "max" && $1 > 0 && $2 > 0 && $1 <= $2)}' /sys/fs/cgroup/cpu.max
task_out=$(mktemp -d /tmp/yblod-batched.XXXXXX)
task_cc=$task_tc/bin/x86_64-libreelec-linux-gnu-gcc
"$task_cc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow -UNDEBUG \
  -I"$task_engine" "$task_lab/test_batched_planes.c" -o "$task_out/ownership"
"$task_sr/usr/lib/ld-linux-x86-64.so.2" --library-path "$task_sr/usr/lib" "$task_out/ownership"
"$task_cc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow -UNDEBUG \
  -ffunction-sections -fdata-sections -Wl,--gc-sections \
  -I"$task_engine" -I/repo/engine/experimental -I/repo/engine/include "$task_lab/native_planar_materialize_probe.c" -o "$task_out/materialize"
"$task_sr/usr/lib/ld-linux-x86-64.so.2" --library-path "$task_sr/usr/lib" "$task_out/materialize"
"$task_cc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow -UNDEBUG \
  -ffunction-sections -fdata-sections -Wl,--gc-sections \
  -I"$task_engine" -I/repo/engine/experimental -I/repo/engine/include "$task_lab/test_batched_options.c" -o "$task_out/options"
"$task_sr/usr/lib/ld-linux-x86-64.so.2" --library-path "$task_sr/usr/lib" "$task_out/options"
"$task_cc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow \
  -I"$task_engine" -I/repo/engine/experimental -I/repo/engine/include -c "$task_engine/native_playback_context.c" -o "$task_out/context.o"
"$task_cc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow \
  -I"$task_engine" -c "$task_engine/native_egl_output_bridge.c" -o "$task_out/bridge.o"
if [ "${1:-}" = --gpu ]; then
  "$task_cc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror \
    -I"$task_engine" "$task_lab/native_planar_sibling_probe.c" \
    "$task_engine/native_egl_output_bridge.c" -o "$task_out/sibling" -lEGL -lGLESv2
  export __EGL_VENDOR_LIBRARY_FILENAMES="$task_sr/usr/share/glvnd/egl_vendor.d/50_mesa.json"
  "$task_sr/usr/lib/ld-linux-x86-64.so.2" --library-path "$task_sr/usr/lib" "$task_out/sibling" /dev/dri/renderD128
fi
for task_field in memory.peak memory.events memory.swap.current; do
  printf '%s: ' "$task_field"
  sed -n '1,20p' "/sys/fs/cgroup/$task_field"
done
