#!/bin/bash
set -euo pipefail
finish() {
 task_exit=$?;trap - EXIT;task_peak=$(cat /sys/fs/cgroup/memory.peak)
 printf 'fixture_exit=%s\npeak_bytes=%s\n' "$task_exit" "$task_peak";cat /sys/fs/cgroup/memory.events
 printf 'swap_current_bytes=%s\nswap_peak_bytes=%s\n' "$(cat /sys/fs/cgroup/memory.swap.current)" "$(cat /sys/fs/cgroup/memory.swap.peak)"
 test "$task_peak" -gt 0 && test "$task_peak" -le 536870912 || task_exit=2
 while read -r task_event task_count;do test "$task_count" = 0 || task_exit=2;done < /sys/fs/cgroup/memory.events
 test "$(cat /sys/fs/cgroup/memory.swap.current)" = 0 && test "$(cat /sys/fs/cgroup/memory.swap.peak)" = 0 || task_exit=2
 exit "$task_exit"
}
trap finish EXIT
test "$(cat /sys/fs/cgroup/memory.max)" = 536870912
test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
read -r task_quota task_period < /sys/fs/cgroup/cpu.max
test "$task_quota" != max && test "$task_quota" -gt 0 && test "$task_period" -gt 0 && test "$task_quota" -le "$task_period"
task_sdk=${SDK_ROOT:?};task_source=${INTEGRATION_SOURCE_DIR:?};task_output=${PROBE_OUTPUT:?};task_public=${PUBLIC_ROOT:?}
task_lib=$task_sdk/x86_64-libreelec-linux-gnu/sysroot/usr/lib
task_flags=(-std=c11 -D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -O2 -fno-lto -fuse-ld=bfd -I"$task_public/tools/yblod/reference")
"$task_sdk/bin/x86_64-libreelec-linux-gnu-gcc" "${task_flags[@]}" "$task_source/test_native_qsv_bl_payload_guard.c" -o "$task_output/test_payload"
"$task_lib/ld-linux-x86-64.so.2" --library-path "$task_lib" "$task_output/test_payload"
"$task_sdk/bin/x86_64-libreelec-linux-gnu-gcc" "${task_flags[@]}" "$task_source/test_native_qsv_bl_pair_coverage.c" -lavformat -lavcodec -lavutil -o "$task_output/test_pairs"
"$task_lib/ld-linux-x86-64.so.2" --library-path "$task_lib" "$task_output/test_pairs"
sha256sum "$task_output/test_payload" "$task_output/test_pairs" "$task_source/native_qsv_bl_compare_probe.c" "$task_source/native_qsv_bl_payload_guard.h" "$task_source/native_qsv_bl_pair_coverage.h" "$task_source/test_native_qsv_bl_payload_guard.c" "$task_source/test_native_qsv_bl_pair_coverage.c"
