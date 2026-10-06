#!/bin/bash
set -euo pipefail
umask 077
test "$(cat /sys/fs/cgroup/memory.max)" = 536870912
test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
read -r task_quota task_period < /sys/fs/cgroup/cpu.max
test "$task_quota" != max && test "$task_quota" -le "$task_period"
task_sdk=${SDK_ROOT:?}; task_source=${TRACE_SOURCE_ROOT:?}; task_out=${TRACE_OUTPUT:?}
task_lib=$task_sdk/x86_64-libreelec-linux-gnu/sysroot/usr/lib
task_cc=$task_sdk/bin/x86_64-libreelec-linux-gnu-gcc
task_flags=(-std=c11 -D_DEFAULT_SOURCE -Wall -Wextra -Werror -O2 -fno-lto -fuse-ld=bfd)
"$task_cc" "${task_flags[@]}" -fPIC -shared "$task_source/native_qsv_mfx_init_trace.c" -ldl -pthread -o "$task_out/native_qsv_mfx_init_trace.so"
"$task_cc" "${task_flags[@]}" "$task_source/test_native_qsv_mfx_init_trace.c" -pthread -o "$task_out/test_native_qsv_mfx_init_trace"
"$task_lib/ld-linux-x86-64.so.2" --library-path "$task_lib" "$task_out/test_native_qsv_mfx_init_trace"
"$task_cc" "${task_flags[@]}" -fPIC -shared "$task_source/native_qsv_mfx_mock_dispatch.c" -Wl,--version-script="$task_source/native_qsv_mfx_mock_dispatch.map" -Wl,-soname,libqsv-mock-dispatch.so -o "$task_out/libqsv-mock-dispatch.so"
"$task_cc" "${task_flags[@]}" "$task_source/test_native_qsv_mfx_loader.c" -L"$task_out" -lqsv-mock-dispatch -o "$task_out/test_native_qsv_mfx_loader"
task_temp=$(mktemp -d)
trap 'rm -f "$task_temp/trace.json"; rmdir "$task_temp"' EXIT
PRIVATE_MFX_INIT_TRACE_PATH="$task_temp/trace.json" "$task_lib/ld-linux-x86-64.so.2" --library-path "$task_out:$task_lib" --preload "$task_out/native_qsv_mfx_init_trace.so" "$task_out/test_native_qsv_mfx_loader"
sha256sum "$task_out/native_qsv_mfx_init_trace.so" "$task_out/test_native_qsv_mfx_init_trace" "$task_out/test_native_qsv_mfx_loader"
task_peak=$(cat /sys/fs/cgroup/memory.peak)
test "$task_peak" -gt 0 && test "$task_peak" -le 536870912
test "$(cat /sys/fs/cgroup/memory.swap.current)" = 0 && test "$(cat /sys/fs/cgroup/memory.swap.peak)" = 0
while read -r task_key task_count; do test "$task_count" = 0; done < /sys/fs/cgroup/memory.events
printf '%s\n' "$task_peak"
cat /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.swap.current /sys/fs/cgroup/memory.swap.peak
