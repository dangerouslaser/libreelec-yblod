#!/bin/sh
set -eu
task_dir=$1
fast=$2
iw=$3
ih=$4
case "$fast" in 0|1) ;; *) exit 2;; esac
case "$iw:$ih" in 32:32|1920:1080) ;; *) exit 2;; esac
binary=/storage/yblod-scaler-flag-20261006/probe
test "$(sha256sum "$binary" | cut -d' ' -f1)" = 98c28481d4e5d2e793bc05458d28e5d06ab11aed085f4f0cdb8fdaaa5991830a
cd "$task_dir"
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
  sha256sum "$binary" "$0" /usr/lib/libva.so.2 /usr/lib/libva-drm.so.2 /usr/lib/libdrm.so.2 /usr/lib/dri/iHD_drv_video.so /usr/lib/libc.so.6 /usr/lib/ld-linux-x86-64.so.2 > "$phase-hashes.txt"
  systemctl show kodi -p ActiveState -p MainPID > "$phase-kodi.txt"
  test "$(systemctl show kodi -p ActiveState --value)" = active
  kodi_pid=$(systemctl show kodi -p MainPID --value)
  test "$kodi_pid" -gt 0
  awk '{print $22}' "/proc/$kodi_pid/stat" > "$phase-kodi-startticks.txt"
  for attribute in gt_cur_freq_mhz gt_act_freq_mhz; do
    if test -r "/sys/class/drm/card0/$attribute"; then
      cat "/sys/class/drm/card0/$attribute" > "$phase-$attribute"
    fi
  done
  if test "$phase" = before; then
    set +e
    "$binary" /dev/dri/renderD128 "$fast" "$iw" "$ih" "$task_dir/output.p010" > result.json 2> driver-stderr.txt
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
