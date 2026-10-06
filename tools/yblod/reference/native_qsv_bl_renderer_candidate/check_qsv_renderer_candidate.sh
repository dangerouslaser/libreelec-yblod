#!/bin/sh
set -eu
# SDK is read-only; patching and object output are confined to disposable /tmp.
test "$#" = 2 || { echo 'usage: check_qsv_renderer_candidate.sh LIBREELEC_ROOT IMAGE' >&2; exit 2; }
sdk=$(realpath "$1")
image=$2
reference=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sudo docker run --rm --memory=512m --memory-swap=512m --cpus=1 --network=none \
  --read-only --tmpfs /tmp:rw,nosuid,exec,size=64m --user 0:0 \
  -e CCACHE_DISABLE=1 -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$sdk:/build:ro" -v "$(dirname "$reference"):/reference:ro" \
  --entrypoint /bin/sh "$image" -c '
    set -eu
    kodi=/build/build.LibreELEC-Generic.x86_64-13.0-devel/build/kodi-22.0rc1-Piers
    ref=/reference/native_qsv_bl_renderer_candidate
    python3 "$ref/stage_qsv_renderer_private.py" "$kodi" "$ref" /tmp/candidate
    python3 "$ref/test_qsv_renderer_source.py" /tmp/candidate
    python3 "$ref/compile_qsv_renderer_candidate.py" "$kodi" /tmp/candidate
    peak=$(cat /sys/fs/cgroup/memory.peak)
    test "$peak" -gt 0 && test "$peak" -le 536870912
    awk "\$2 != 0 {bad=1} END {exit bad}" /sys/fs/cgroup/memory.events
    test "$(cat /sys/fs/cgroup/memory.swap.current)" = 0
    echo "memory_peak=$peak"
    cat /sys/fs/cgroup/memory.events
    echo swap_current=0
  '
