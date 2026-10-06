#!/bin/sh
# Isolated diagnostic only. Root must pin transported artifacts before invoking.
set -eu
task_dir=$1
fixture=$2
shader=$3
binary=$4
width=$5
height=$6
binary_sha=$7
shader_sha=$8
test "$(sha256sum "$binary" | cut -d' ' -f1)" = "$binary_sha"
test "$(sha256sum "$shader" | cut -d' ' -f1)" = "$shader_sha"
cd "$task_dir"
test ! -e result.json
group=$(awk -F: '$1=="0" {print $3}' /proc/self/cgroup)
cgroup="/sys/fs/cgroup$group"
test "$(cat "$cgroup/memory.max")" = 536870912
test "$(cat "$cgroup/memory.swap.max")" = 0
test "$(cat "$cgroup/memory.swap.current")" = 0
awk '$2!=0 {exit 1}' "$cgroup/memory.events"
status=0
for phase in before after; do
  for field in memory.max memory.peak memory.events memory.swap.current memory.swap.max cpu.max cpu.stat; do
    cp "$cgroup/$field" "$phase-$field"
  done
  sha256sum "$binary" "$shader" "$0" "$fixture/instructions.bin" \
    "$fixture/bl_Y.u16le" "$fixture/bl_Cb.u16le" "$fixture/bl_Cr.u16le" \
    "$fixture/mmr_luma.u16le" "$fixture/scaled1.p010" \
    /usr/lib/libEGL.so.1 /usr/lib/libEGL_mesa.so.0 /usr/lib/libGLdispatch.so.0 \
    /usr/lib/libgallium-26.2.4.so /usr/lib/libgbm.so.1 /usr/lib/libdrm.so.2 \
    /usr/lib/libc.so.6 /usr/lib/ld-linux-x86-64.so.2 > "$phase-hashes.txt"
  systemctl show kodi -p ActiveState -p MainPID > "$phase-kodi.txt"
  test "$(systemctl show kodi -p ActiveState --value)" = active
  kodi_pid=$(systemctl show kodi -p MainPID --value)
  test "$kodi_pid" -gt 0
  awk '{print $22}' "/proc/$kodi_pid/stat" > "$phase-kodi-startticks.txt"
  for field in gt_cur_freq_mhz gt_act_freq_mhz; do
    if test -r "/sys/class/drm/card0/$field"; then
      cat "/sys/class/drm/card0/$field" > "$phase-$field"
    fi
  done
  if test "$phase" = before; then
    set +e
    "$binary" /dev/dri/renderD128 "$shader" "$width" "$height" \
      "$fixture/instructions.bin" "$fixture/bl_Y.u16le" "$fixture/bl_Cb.u16le" \
      "$fixture/bl_Cr.u16le" "$fixture/mmr_luma.u16le" "$fixture/scaled1.p010" \
      "$task_dir/output.u16le" > result.json 2> stderr.txt
    status=$?
    set -e
    printf '%s\n' "$status" > probe-exit.txt
  fi
done
for field in hashes.txt kodi.txt kodi-startticks.txt; do
  test "$(sha256sum "before-$field" | cut -d' ' -f1)" = "$(sha256sum "after-$field" | cut -d' ' -f1)"
done
test "$(cat "$cgroup/memory.swap.current")" = 0
awk '$2!=0 {exit 1}' "$cgroup/memory.events"
cat result.json
exit "$status"
