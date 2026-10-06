#!/bin/bash
# CPU build only; preserves the separate authoritative comparison probe.
set -euo pipefail
test "$(cat /sys/fs/cgroup/memory.max)" = 536870912
test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
read -r quota period < /sys/fs/cgroup/cpu.max
test "$quota" != max && test "$quota" -le "$period"
task_sdk=${SDK_ROOT:?}
task_public=${PUBLIC_ROOT:?}
task_output=${PROBE_OUTPUT:?}
task_helper=${EL_HELPER_SOURCE:?}
task_headers=${EL_HELPER_INCLUDE:?}
task_libs="$task_sdk/x86_64-libreelec-linux-gnu/sysroot/usr/lib"
task_sources="$task_public/tools/yblod/reference"
task_flags=(-std=c11 -D_POSIX_C_SOURCE=200809L -D_DEFAULT_SOURCE -Wall -Wextra -Werror -O2 -fno-lto -fuse-ld=bfd
  -I"$task_headers" -I"$task_sources" -I"$task_sdk/x86_64-libreelec-linux-gnu/sysroot/usr/include")
for task_source in native_qsv_el_header_init_probe test_native_qsv_el_annexb_guard; do
  task_extra=()
  if test "$task_source" = native_qsv_el_header_init_probe; then
    task_extra=("$task_helper" -Wl,--wrap=avcodec_send_packet)
  fi
  "$task_sdk/bin/x86_64-libreelec-linux-gnu-gcc" "${task_flags[@]}" \
    "$task_sources/$task_source.c" "${task_extra[@]}" \
    -L"$task_libs" -lavformat -lavcodec -lavutil -o "$task_output/$task_source"
done
export EXPECTED_CPU_AVUTIL=$(readlink -f "$task_libs/libavutil.so")
"$task_libs/ld-linux-x86-64.so.2" --library-path "$task_libs:$task_sdk/x86_64-libreelec-linux-gnu/lib" \
  "$task_output/test_native_qsv_el_annexb_guard"
sha256sum "$task_output/native_qsv_el_header_init_probe" "$task_output/test_native_qsv_el_annexb_guard"
task_peak=$(cat /sys/fs/cgroup/memory.peak)
test "$task_peak" -gt 0 && test "$task_peak" -le 536870912
test "$(cat /sys/fs/cgroup/memory.swap.current)" = 0
test "$(cat /sys/fs/cgroup/memory.swap.peak)" = 0
while read -r task_event task_count; do test "$task_count" = 0; done < /sys/fs/cgroup/memory.events
printf '%s\n' "$task_peak"
cat /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.swap.current /sys/fs/cgroup/memory.swap.peak
