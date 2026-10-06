#!/bin/bash
set -euo pipefail
finish() {
 task_exit=$?;trap - EXIT
 task_peak=$(cat /sys/fs/cgroup/memory.peak)
 printf 'fixture_exit=%s\npeak_bytes=%s\n' "$task_exit" "$task_peak"
 cat /sys/fs/cgroup/memory.events
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
task_sdk=${SDK_ROOT:?};task_source=${ADMISSION_SOURCE_DIR:?};task_public=${PUBLIC_ROOT:?};task_output=${PROBE_OUTPUT:?}
task_lib=$task_sdk/x86_64-libreelec-linux-gnu/sysroot/usr/lib
"$task_sdk/bin/x86_64-libreelec-linux-gnu-gcc" -std=c11 -D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -O2 -fno-lto -fuse-ld=bfd -I"$task_public/tools/yblod/reference" "$task_source/test_native_qsv_bl_probe_admission.c" -lavformat -lavcodec -lavutil -o "$task_output/test_bl_admission"
"$task_lib/ld-linux-x86-64.so.2" --library-path "$task_lib" "$task_output/test_bl_admission"
sha256sum "$task_output/test_bl_admission" "$task_source/test_native_qsv_bl_probe_admission.c" "$task_source/native_qsv_bl_compare_probe.c"
