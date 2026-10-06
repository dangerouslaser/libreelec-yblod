#!/bin/bash
# SDK foundation only. This does not install/restart Kodi or change its decoder.
# Root must approve the dedicated build window and source synchronization first.
set -euo pipefail
test "$(sed -n '1p' /sys/fs/cgroup/memory.max)" = 4294967296
test "$(sed -n '1p' /sys/fs/cgroup/memory.swap.max)" = 0
awk '{exit !($1 != "max" && $1 > 0 && $2 > 0 && $1 <= $2)}' /sys/fs/cgroup/cpu.max
finish() {
 task_result=$?
 trap - EXIT
 printf 'qsv_sdk_build_exit=%s\n' "$task_result"
 for task_field in memory.max memory.swap.max cpu.max memory.peak memory.events memory.swap.current memory.swap.peak; do
  printf '%s: ' "$task_field"; sed -n '1,20p' "/sys/fs/cgroup/$task_field"
 done
 if ! awk '$2!=0 {exit 1}' /sys/fs/cgroup/memory.events; then task_result=1; fi
 if ! test "$(sed -n '1p' /sys/fs/cgroup/memory.swap.current)" = 0; then task_result=1; fi
 exit "$task_result"
}
trap finish EXIT
cd /build
: "${QSV_SDK_BASELINE_ARCHIVE:?Preserve and verify the pre-QSV configured FFmpeg SDK first}"
python3 - "$QSV_SDK_BASELINE_ARCHIVE" <<'PY'
import hashlib, json, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.is_absolute() or p.name != 'baseline-ffmpeg-sdk.tar' or not p.is_file() or p.is_symlink():
    raise SystemExit('invalid private baseline archive')
m = json.loads(p.with_suffix('.json').read_text())
if m.get('schema') != 'yblod.ffmpeg-sdk-baseline.v1' or m.get('complete') is not True or m.get('libvpl_enabled') is not False:
    raise SystemExit('baseline manifest not qualified')
h = hashlib.sha256()
with p.open('rb') as f:
    for chunk in iter(lambda: f.read(1024*1024), b''):
        h.update(chunk)
if h.hexdigest() != m.get('archive_sha256') or p.stat().st_size != m.get('archive_bytes'):
    raise SystemExit('baseline archive hash/extent mismatch')
print('pre_qsv_sdk_baseline_archive_verified=1')
PY
export PROJECT=Generic DEVICE=Generic ARCH=x86_64 YBLOD_QSV_DECODE=yes
export CONCURRENCY_MAKE_LEVEL=1 CONCURRENCY_LOAD=1 CMAKE_BUILD_PARALLEL_LEVEL=1
export MAKEFLAGS=-j1 NINJA_OPTS=-j1 DEFAULT_LINKER=bfd
export MTWITHLOCKS=no
# Network-disabled build: reviewed official archives must already be cached.
printf '%s\n' \
 '4de3e2faf1e8307fb282e4a43f443191810f6a6b0a484fffa7995ba1c814c6ec  sources/libvpl/libvpl-2.17.0.tar.gz' \
 '92867a0f8c09d81419102a61713e9f98dfd2af3fc9c91c6f4fb6d0c784c8e442  sources/vpl-gpu-rt/vpl-gpu-rt-26.3.5.tar.gz' \
 '8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e  sources/ffmpeg/ffmpeg-9.0.2.tar.xz' | sha256sum -c -
task_sdk=/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain/x86_64-libreelec-linux-gnu/sysroot
task_driver="$task_sdk/usr/lib/dri/iHD_drv_video.so"
task_before_driver=$(sha256sum "$task_driver" | cut -d ' ' -f1)
# The dependency recipes do not rebuild or replace media-driver.
scripts/build libvpl
scripts/build vpl-gpu-rt
scripts/build ffmpeg
task_after_driver=$(sha256sum "$task_driver" | cut -d ' ' -f1)
test "$task_before_driver" = "$task_after_driver"
task_ffmpeg=/build/build.LibreELEC-Generic.x86_64-13.0-devel/build/ffmpeg-9.0.2
grep -qx '#define CONFIG_LIBVPL 1' "$task_ffmpeg/config.h"
grep -qx '#define CONFIG_QSV 1' "$task_ffmpeg/config.h"
grep -qx '#define CONFIG_VAAPI 1' "$task_ffmpeg/config.h"
grep -qx '#define CONFIG_HEVC_QSV_DECODER 1' "$task_ffmpeg/config_components.h"
test -f "$task_sdk/usr/lib/libvpl.so.2"
test -f "$task_sdk/usr/lib/libmfx-gen.so.1.2"
printf 'qsv_sdk_foundation_complete=1\nexisting_media_driver_unchanged=1\n'
# Capability/library presence is not proof of runtime discovery or direct maps.
printf 'qsv_runtime_discovery_qualified=0\nkodi_playback_qualified=0\n'
