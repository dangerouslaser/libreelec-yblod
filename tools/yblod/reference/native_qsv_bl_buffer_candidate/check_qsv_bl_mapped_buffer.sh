#!/bin/sh
# Usage: sh check_qsv_bl_mapped_buffer.sh /absolute/LibreELEC/SDK/project
set -eu
test "$#" = 1
test -d "$1"
sdk_project=$(CDPATH= cd -- "$1" && pwd)
fixture=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
docker run --rm --memory=512m --memory-swap=512m --cpus=1 --network=none \
  --read-only --tmpfs /tmp:rw,nosuid,exec,size=32m --user 0:0 \
  -e CCACHE_DISABLE=1 -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$sdk_project:/build:ro" -v "$fixture:/lab:ro" --entrypoint /bin/sh \
  "${QDA_TEST_IMAGE:-libreelec-dv-build:latest}" -c '
set -eu
python3 /lab/compile_qsv_mapped_buffer_private.py
python3 /lab/run_qsv_mapped_buffer_private.py
awk '\''$2 != 0 {exit 1}'\'' /sys/fs/cgroup/memory.events
test "$(cat /sys/fs/cgroup/memory.swap.current)" = 0
peak=$(cat /sys/fs/cgroup/memory.peak)
test "$peak" -gt 0
test "$peak" -le 536870912
sha256sum /lab/QsvMappedBuffer.h /lab/QsvMappedBuffer.cpp /lab/test_qsv_mapped_buffer_private.cpp
echo memory_peak_bytes
echo "$peak"
echo memory_events
cat /sys/fs/cgroup/memory.events
echo swap_bytes
cat /sys/fs/cgroup/memory.swap.current
'
