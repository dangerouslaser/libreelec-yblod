#!/bin/sh
# CPU-only test; invoke with docker access and no additional GPU mounts.
set -eu
fixture=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
docker run --rm --memory=512m --memory-swap=512m --cpus=1 --network=none \
  --read-only --user 0:0 --tmpfs /tmp:rw,nosuid,exec,size=16m \
  -v "$fixture:/fixture:ro" --entrypoint /bin/sh \
  "${QDA_TEST_IMAGE:-yblod-ffmpeg9-decode:9.0.2}" -c '
set -eu
cc -std=c11 -Wall -Wextra -Werror -ffunction-sections -fdata-sections \
  -I/opt/ffmpeg-source /fixture/test_qsv_dovi_context_clone.c \
  /opt/ffmpeg-source/libavcodec/dovi_rpu.o \
  /opt/ffmpeg-source/libavutil/libavutil.a \
  -Wl,--gc-sections -lm -lpthread -ldl -o /tmp/test
/tmp/test
awk '\''$2 != 0 {exit 1}'\'' /sys/fs/cgroup/memory.events
test "$(cat /sys/fs/cgroup/memory.swap.current)" = 0
peak=$(cat /sys/fs/cgroup/memory.peak)
test "$peak" -gt 0
test "$peak" -le 536870912
sha256sum /fixture/qsv_dovi_context_clone.h /fixture/test_qsv_dovi_context_clone.c
echo memory_peak_bytes
cat /sys/fs/cgroup/memory.peak
echo memory_events
cat /sys/fs/cgroup/memory.events
echo swap_bytes
cat /sys/fs/cgroup/memory.swap.current
'
