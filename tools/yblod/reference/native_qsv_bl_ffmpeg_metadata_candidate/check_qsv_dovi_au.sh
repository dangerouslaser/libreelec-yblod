#!/bin/sh
# Private input is one complete HEVC type62 NAL, WITHOUT an AnnexB delimiter.
set -eu
test "$#" = 1 && test -f "$1"
fixture=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
input=$(realpath "$1")
docker run --rm --memory=512m --memory-swap=512m --cpus=1 --network=none \
  --read-only --user 0:0 --tmpfs /tmp:rw,nosuid,exec,size=16m \
  -v "$fixture:/fixture:ro" -v "$input:/private-input:ro" --entrypoint /bin/sh \
  "${QDA_TEST_IMAGE:-yblod-ffmpeg9-decode:9.0.2}" -c '
set -eu
cc -std=c11 -Wall -Wextra -Werror -I/opt/ffmpeg-source -I/opt/ffmpeg-source/libavcodec \
  /fixture/test_qsv_dovi_au.c /opt/ffmpeg-source/libavcodec/libavcodec.a \
  /opt/ffmpeg-source/libavutil/libavutil.a -lvpl -lva -lva-drm -lm -lpthread -ldl -o /tmp/test
/tmp/test /private-input 2>/tmp/private-parser-log
awk '\''$2 != 0 {exit 1}'\'' /sys/fs/cgroup/memory.events
test "$(cat /sys/fs/cgroup/memory.swap.current)" = 0
peak=$(cat /sys/fs/cgroup/memory.peak)
test "$peak" -gt 0 && test "$peak" -le 536870912
sha256sum /fixture/qsv_dovi.h /fixture/test_qsv_dovi_au.c
echo memory_peak_bytes="$peak"
cat /sys/fs/cgroup/memory.events
echo swap_current_bytes=0
'
