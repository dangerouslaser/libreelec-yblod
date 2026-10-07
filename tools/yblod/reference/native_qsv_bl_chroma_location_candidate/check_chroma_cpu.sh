#!/bin/sh
set -eu
test "$(cat /sys/fs/cgroup/memory.max)" -eq 536870912
test "$(cat /sys/fs/cgroup/memory.swap.max)" -eq 0
cc -std=c11 -Wall -Wextra -Werror -Wno-sign-compare -include /opt/ffmpeg-source/libavutil/internal.h -I/candidate -I/opt/ffmpeg-source -I/opt/ffmpeg-source/libavcodec /candidate/test_qsv_chroma.c /opt/ffmpeg-source/libavcodec/libavcodec.a /opt/ffmpeg-source/libavutil/libavutil.a -lvpl -lva -lva-drm -lm -lpthread -ldl -o /tmp/chroma
/tmp/chroma
cc -std=c11 -Wall -Wextra -Werror -Wno-sign-compare -include /opt/ffmpeg-source/libavutil/internal.h -I/candidate -I/opt/ffmpeg-source -I/opt/ffmpeg-source/libavcodec /candidate/test_qsv_dovi_key.c /opt/ffmpeg-source/libavcodec/libavcodec.a /opt/ffmpeg-source/libavutil/libavutil.a -lvpl -lva -lva-drm -lm -lpthread -ldl -o /tmp/key
/tmp/key
test "$(cat /sys/fs/cgroup/memory.swap.peak)" -eq 0
awk '$2!=0 {bad=1} END {exit bad}' /sys/fs/cgroup/memory.events
echo memory_peak=$(cat /sys/fs/cgroup/memory.peak)
