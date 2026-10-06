#!/bin/bash
# Run only after hardware approval in a 512MiB/noSwap/CPU1/networknone container.
# Mount the requested private media and render node explicitly; no raw exports.
set -euo pipefail
umask 077
test "$(cat /sys/fs/cgroup/memory.max)" = 536870912
test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
read -r quota period < /sys/fs/cgroup/cpu.max
test "$quota" != max && test "$quota" -le "$period"
task_sdk=${SDK_ROOT:?SDK_ROOT required}
task_binary=${PROBE_BINARY:?PROBE_BINARY required}
task_expected=${EXPECTED_PROBE_SHA256:?EXPECTED_PROBE_SHA256 required}
task_log=${PRIVATE_DIAGNOSTIC_LOG:?fresh private diagnostic filename required}
test "${#task_expected}" = 64
test "$(sha256sum "$task_binary" | cut -d' ' -f1)" = "$task_expected"
test ! -e "$task_log"
test ! -L "$task_log"
if test -n "${PRIVATE_PROGRESS_PATH:-}"; then
  test ! -e "$PRIVATE_PROGRESS_PATH" && test ! -L "$PRIVATE_PROGRESS_PATH"
fi
test "$#" = 4
case "$4" in derived36|derived0|direct36|derived36-elheaders) ;; *) exit 2 ;; esac
test -n "${PRIVATE_AU_IDENTITY_PATH:-}"
test ! -e "$PRIVATE_AU_IDENTITY_PATH" && test ! -L "$PRIVATE_AU_IDENTITY_PATH"
task_libs="$task_sdk/x86_64-libreelec-linux-gnu/sysroot/usr/lib"
# Decoder messages may contain private media information. Never print them.
set -o noclobber
exec 2>"$task_log"
export ONEVPL_PRIORITY_PATH="$task_libs"
export LIBVA_DRIVERS_PATH="$task_libs/dri"
export LIBVA_DRIVER_NAME=iHD
export EXPECTED_QSV_LIBVPL="$task_libs/libvpl.so.2.17"
export EXPECTED_QSV_IMPLEMENTATION="$task_libs/libmfx-gen.so.1.2.17"
export EXPECTED_QSV_VA_DRIVER="$task_libs/dri/iHD_drv_video.so"
test -f "$EXPECTED_QSV_LIBVPL" && test -f "$EXPECTED_QSV_IMPLEMENTATION" && test -f "$EXPECTED_QSV_VA_DRIVER"
task_preload=()
if test -n "${MFX_TRACE_INTERPOSER:-}"; then
  test "$(sha256sum "$MFX_TRACE_INTERPOSER" | cut -d' ' -f1)" = "${EXPECTED_MFX_TRACE_SHA256:?}"
  test -n "${PRIVATE_MFX_INIT_TRACE_PATH:-}"
  test ! -e "$PRIVATE_MFX_INIT_TRACE_PATH" && test ! -L "$PRIVATE_MFX_INIT_TRACE_PATH"
  task_preload=(--preload "$MFX_TRACE_INTERPOSER")
fi
set +e
"$task_libs/ld-linux-x86-64.so.2" \
  --library-path "$task_libs:$task_sdk/x86_64-libreelec-linux-gnu/lib" "${task_preload[@]}" "$task_binary" "$@"
task_status=$?
set -e
# Resource evidence is scalar and separate from the probe's JSON document.
printf 'probe_exit=%s\n' "$task_status"
cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events
task_peak=$(cat /sys/fs/cgroup/memory.peak)
test "$task_peak" -gt 0 && test "$task_peak" -le 536870912
while read -r task_event task_value; do
  test "$task_value" = 0
done < /sys/fs/cgroup/memory.events
test "$(cat /sys/fs/cgroup/memory.swap.current)" = 0
test "$(cat /sys/fs/cgroup/memory.swap.peak)" = 0
exit "$task_status"
