#!/bin/sh
set -eu
test "$(cat /sys/fs/cgroup/memory.max)" -eq 536870912
test "$(cat /sys/fs/cgroup/memory.swap.max)" -eq 0
awk '$1=="max"||$1<=0||$2<=0||$1>$2 {exit 1}' /sys/fs/cgroup/cpu.max
cc -std=c11 -Wall -Wextra -Werror -I/candidate -I/opt/ffmpeg-source -I/opt/ffmpeg-source/libavcodec /candidate/test_qsv_dovi_au.c /opt/ffmpeg-source/libavcodec/libavcodec.a /opt/ffmpeg-source/libavutil/libavutil.a -lvpl -lva -lva-drm -lm -lpthread -ldl -o /tmp/au
/tmp/au /private-input 2>/tmp/private-parser-log
test "$(cat /sys/fs/cgroup/memory.swap.peak)" -eq 0
awk '$2!=0 {bad=1} END {exit bad}' /sys/fs/cgroup/memory.events
echo memory_peak=$(cat /sys/fs/cgroup/memory.peak)
