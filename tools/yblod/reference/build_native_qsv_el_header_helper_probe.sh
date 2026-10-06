#!/bin/bash
# CPU-only helper contracts and comparison build; does not run hardware.
set -euo pipefail
test "$(cat /sys/fs/cgroup/memory.max)" = 536870912
test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
read -r task_quota task_period < /sys/fs/cgroup/cpu.max
test "$task_quota" != max && test "$task_quota" -le "$task_period"
task_sdk=${SDK_ROOT:?};task_public=${PUBLIC_ROOT:?};task_out=${PROBE_OUTPUT:?}
task_helper=${EL_HELPER_SOURCE:?};task_include=${EL_HELPER_INCLUDE:?}
task_lib=$task_sdk/x86_64-libreelec-linux-gnu/sysroot/usr/lib
task_cc=$task_sdk/bin/x86_64-libreelec-linux-gnu-gcc
task_flags=(-std=c11 -D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -O2 -fno-lto -fuse-ld=bfd -I"$task_include")
"$task_cc" "${task_flags[@]}" -DYB_FEL_SOURCE="\"$task_helper\"" "$task_public/tools/yblod/reference/test_qsv_header_fel.c" -lavcodec -lavutil -o "$task_out/test_qsv_header_fel"
"$task_lib/ld-linux-x86-64.so.2" --library-path "$task_lib" "$task_out/test_qsv_header_fel"
"$task_cc" "${task_flags[@]}" "$task_public/tools/yblod/reference/test_native_qsv_probe_handshake.c" -o "$task_out/test_native_qsv_probe_handshake"
"$task_lib/ld-linux-x86-64.so.2" --library-path "$task_lib" "$task_out/test_native_qsv_probe_handshake"
"$task_cc" "${task_flags[@]}" "$task_public/tools/yblod/reference/native_qsv_el_compare_probe.c" "$task_helper" -lavformat -lavcodec -lavutil -o "$task_out/native_qsv_el_header_compare_probe"
sha256sum "$task_out/native_qsv_el_header_compare_probe" "$task_out/test_qsv_header_fel" "$task_out/test_native_qsv_probe_handshake"
task_peak=$(cat /sys/fs/cgroup/memory.peak)
test "$task_peak" -gt 0 && test "$task_peak" -le 536870912
while read -r task_event task_count;do test "$task_count" = 0;done < /sys/fs/cgroup/memory.events
test "$(cat /sys/fs/cgroup/memory.swap.current)" = 0 && test "$(cat /sys/fs/cgroup/memory.swap.peak)" = 0
printf '%s\n' "$task_peak"
cat /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.swap.current /sys/fs/cgroup/memory.swap.peak
