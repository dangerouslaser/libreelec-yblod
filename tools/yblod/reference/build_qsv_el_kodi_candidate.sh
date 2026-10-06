#!/bin/sh
# Run only after source preparation is approved, inside the bounded SDK container.
set -eu
finish() {
  result=$?
  trap - EXIT
  echo build_exit="$result"
  for field in memory.peak memory.events memory.swap.current memory.swap.peak; do
    echo "$field"; cat "/sys/fs/cgroup/$field"
  done
  test "$(cat /sys/fs/cgroup/memory.swap.current)" = 0 || result=1
  test "$(cat /sys/fs/cgroup/memory.swap.peak)" = 0 || result=1
  awk '$2!=0 {exit 1}' /sys/fs/cgroup/memory.events || result=1
  exit "$result"
}
trap finish EXIT
test "$(cat /sys/fs/cgroup/memory.max)" = 4294967296
test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
awk '$1=="max" || $1<=0 || $2<=0 || $1>$2 {exit 1}' /sys/fs/cgroup/cpu.max
test -z "$(find /dev/dri -type c 2>/dev/null)"
sdk=/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain
kodi=/build/build.LibreELEC-Generic.x86_64-13.0-devel/build/kodi-22.0rc1-Piers
ffmpeg=/build/build.LibreELEC-Generic.x86_64-13.0-devel/build/ffmpeg-9.0.2
grep -q '^#define CONFIG_LIBVPL 1$' "$ffmpeg/config.h"
grep -q '^#define CONFIG_QSV 1$' "$ffmpeg/config.h"
grep -q '^#define CONFIG_HEVC_QSV_DECODER 1$' "$ffmpeg/config_components.h"
grep -q '^#define CONFIG_VAAPI 1$' "$ffmpeg/config.h"
grep -q '^#define CONFIG_HEVC_VAAPI_HWACCEL 1$' "$ffmpeg/config_components.h"
driver="$sdk/x86_64-libreelec-linux-gnu/sysroot/usr/lib/dri/iHD_drv_video.so"
test "$(sha256sum "$driver" | cut -d' ' -f1)" = d30f166ce5f9949b8195a8f6a4124baa302978b427a3714dcba09b2226cfe798
export PATH="$sdk/bin:$PATH"
export PKG_CONFIG_PATH=
export PKG_CONFIG_LIBDIR="$sdk/x86_64-libreelec-linux-gnu/sysroot/usr/lib/pkgconfig:$sdk/x86_64-libreelec-linux-gnu/sysroot/usr/share/pkgconfig"
export PKG_CONFIG_SYSROOT_DIR="$sdk/x86_64-libreelec-linux-gnu/sysroot"
cd "$kodi/.x86_64-libreelec-linux-gnu"
python3 -c 'import sys,json;sys.path.insert(0,"/lab");from prepare_qsv_el_kodi_build import validate_prepared;from pathlib import Path;validate_prepared(Path("..").resolve(),json.loads(Path("/lab/qsv-el-preparation.private.json").read_text()))'
"$sdk/bin/ninja" -j1 build.ninja
# Generated build-file mechanical edit: only the final Kodi link edge changes.
python3 -c 'import sys;sys.path.insert(0,"/lab");from prepare_qsv_el_kodi_build import serial_link;from pathlib import Path;p=Path("build.ninja");p.write_text(serial_link(p.read_text()))'
"$sdk/bin/ninja" -t commands kodi.bin > /lab/qsv-el-candidate-commands.private.txt
python3 -c 'import sys;sys.path.insert(0,"/lab");from prepare_qsv_el_kodi_build import validate_final_command;from pathlib import Path;validate_final_command(Path("/lab/qsv-el-candidate-commands.private.txt").read_text());print("final_effective_lto_workers=1")'
"$sdk/bin/ninja" -j1 kodi &
build_pid=$!
while kill -0 "$build_pid" 2>/dev/null; do
  workers=$(ps -eo comm | awk '/^lto1(-ltrans)?$/ {n++} END {print n+0}')
  if test "$workers" -gt 1; then
    echo STOP_parallel_LTRANS_workers="$workers"
    kill "$build_pid"
    exit 97
  fi
  sleep 2
done
wait "$build_pid"
"$sdk/bin/ninja" -t commands kodi.bin > /lab/qsv-el-candidate-commands.private.txt
python3 -c 'import sys,json;sys.path.insert(0,"/lab");from prepare_qsv_el_kodi_build import validate_prepared,validate_final_command;from pathlib import Path;validate_prepared(Path("..").resolve(),json.loads(Path("/lab/qsv-el-preparation.private.json").read_text()));validate_final_command(Path("/lab/qsv-el-candidate-commands.private.txt").read_text())'
test "$(sha256sum "$driver" | cut -d' ' -f1)" = d30f166ce5f9949b8195a8f6a4124baa302978b427a3714dcba09b2226cfe798
sha256sum kodi.bin
