#!/bin/sh
set -eu
test "$#" = 1 || { echo 'usage: check_qsv_kodi_integration_candidate.sh SDK_ROOT' >&2; exit 2; }
sdk=$(realpath "$1")
reference=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
docker run --rm --memory=512m --memory-swap=512m --cpus=1 --network=none \
  --read-only --tmpfs /tmp:rw,nosuid,exec,size=64m --user 0:0 \
  -e CCACHE_DISABLE=1 -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$sdk:/build:ro" -v "$(dirname "$reference"):/reference:ro" \
  --entrypoint /bin/sh sha256:40b586615eae489cab72f139f659b81360da4c9e0b0787fadc5cba0119d9b29e -c '
    set -eu
    test "$(cat /sys/fs/cgroup/memory.max)" = 536870912
    test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
    awk "\$1 <= 0 || \$2 <= 0 || \$1 > \$2 {exit 1}" /sys/fs/cgroup/cpu.max
    kodi=/build/build.LibreELEC-Generic.x86_64-13.0-devel/build/kodi-22.0rc1-Piers
    ref=/reference/native_qsv_bl_kodi_integration_candidate
    python3 "$ref/stage_qsv_kodi_integration.py" "$kodi" "$ref" /tmp/candidate
    python3 "$ref/test_qsv_kodi_decoder_source.py" /tmp/candidate
    python3 /reference/native_qsv_bl_renderer_candidate/test_qsv_renderer_source.py /tmp/candidate
    python3 "$ref/compile_qsv_kodi_decoder.py" "$kodi" /tmp/candidate
    peak=$(cat /sys/fs/cgroup/memory.peak)
    test "$peak" -gt 0 && test "$peak" -le 536870912
    awk "\$2 != 0 {bad=1} END {exit bad}" /sys/fs/cgroup/memory.events
    test "$(cat /sys/fs/cgroup/memory.swap.current)" = 0
    test "$(cat /sys/fs/cgroup/memory.swap.peak)" = 0
    echo "memory_peak=$peak"
    cat /sys/fs/cgroup/memory.events
    echo swap_current=0 swap_peak=0
  '
