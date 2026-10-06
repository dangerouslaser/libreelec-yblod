#!/bin/bash
# SDK-native CPU build only. No hardware or media access.
set -euo pipefail
test "$(cat /sys/fs/cgroup/memory.max)" = 536870912
test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
read -r quota period < /sys/fs/cgroup/cpu.max
test "$quota" != max && test "$quota" -le "$period"
task_sdk=${SDK_ROOT:?SDK_ROOT required}
task_public=${PUBLIC_ROOT:?PUBLIC_ROOT required}
task_output=${PROBE_OUTPUT:?PROBE_OUTPUT required}
test -d "$task_output"
task_sysroot="$task_sdk/x86_64-libreelec-linux-gnu/sysroot"
task_source="$task_public/tools/yblod/reference"
# Caller supplies helper source prepared by the published patch19+20 verifier.
task_helper=${EL_HELPER_SOURCE:?EL_HELPER_SOURCE required}
task_headers=${EL_HELPER_INCLUDE:?EL_HELPER_INCLUDE required}
task_flags=(-std=c11 -D_POSIX_C_SOURCE=200809L -D_DEFAULT_SOURCE -Wall -Wextra -Werror -O2 -fno-lto -fuse-ld=bfd
  -I"$task_headers" -I"$task_source" -I"$task_sysroot/usr/include")
"$task_sdk/bin/x86_64-libreelec-linux-gnu-gcc" "${task_flags[@]}" \
  "$task_source/native_qsv_el_compare_probe.c" "$task_helper" \
  -L"$task_sysroot/usr/lib" -lavformat -lavcodec -lavutil -o "$task_output/native-qsv-el-compare-probe"
"$task_sdk/bin/x86_64-libreelec-linux-gnu-gcc" "${task_flags[@]}" \
  "$task_source/test_native_qsv_el_compare_probe.c" "$task_helper" \
  -L"$task_sysroot/usr/lib" -lavformat -lavcodec -lavutil -o "$task_output/test-native-qsv-el-compare-probe"
sha256sum "$task_output/native-qsv-el-compare-probe" "$task_output/test-native-qsv-el-compare-probe"
cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events
