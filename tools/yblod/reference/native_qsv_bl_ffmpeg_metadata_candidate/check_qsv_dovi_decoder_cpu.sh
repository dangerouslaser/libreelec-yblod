#!/bin/sh
set -eu
test "$(cat /sys/fs/cgroup/memory.max)" -eq 536870912
test "$(cat /sys/fs/cgroup/memory.swap.max)" -eq 0
awk '$1 == "max" || $1 <= 0 || $2 <= 0 || $1 > $2 {exit 1}' /sys/fs/cgroup/cpu.max
mode=${1:?mfx, allocator, or gate required}
fixture=${QSV_DOVI_FIXTURE_ROOT:-/fixture}
overlay=$fixture/test_qsv_dovi_config.h
wrap=
case "$mode" in
 mfx) source=$fixture/test_qsv_dovi_mfx.c; wrap='-Wl,--wrap=ff_decode_frame_props -Wl,--wrap=ff_attach_decode_data -Wl,--wrap=ff_get_buffer' ;;
 allocator) python3 "${QSV_DOVI_HELPER_ROOT:-/fixture}/prepare_qsv_allocator_fixture.py"; source=$fixture/test_qsv_dovi_allocator.c ;;
 gate) source=$fixture/test_qsv_dovi_gate.c; overlay=$fixture/test_qsv_dovi_nogpl_config.h ;;
 *) exit 2 ;;
esac
cc -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror \
 -Wno-unused-parameter -Wno-missing-field-initializers -Wno-sign-compare \
 -Wno-unused-const-variable -ffunction-sections -fdata-sections \
 -I/opt/ffmpeg-source -I/opt/ffmpeg-source/libavcodec -I/usr/include/vpl \
 -include "$overlay" "$source" /opt/ffmpeg-source/libavcodec/libavcodec.a \
 /opt/ffmpeg-source/libavutil/libavutil.a -Wl,--gc-sections $wrap \
 -lvpl -lva -lva-drm -lm -lpthread -ldl -o /tmp/test
/tmp/test
peak=$(cat /sys/fs/cgroup/memory.peak)
test "$peak" -gt 0 && test "$peak" -le 536870912
test "$(cat /sys/fs/cgroup/memory.swap.current)" -eq 0
test "$(cat /sys/fs/cgroup/memory.swap.peak)" -eq 0
awk '$2 != 0 {bad=1} END {exit bad}' /sys/fs/cgroup/memory.events
printf 'memory_peak=%s\n' "$peak"
cat /sys/fs/cgroup/memory.events
