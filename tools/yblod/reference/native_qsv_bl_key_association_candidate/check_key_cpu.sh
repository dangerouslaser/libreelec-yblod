#!/bin/sh
# Source-only actual qsv_decode fixture; MFX operations are mocked.
set -eu
test "$(cat /sys/fs/cgroup/memory.max)" -eq 536870912
test "$(cat /sys/fs/cgroup/memory.swap.max)" -eq 0
awk '$1 == "max" || $1 <= 0 || $2 <= 0 || $1 > $2 {exit 1}' /sys/fs/cgroup/cpu.max
cd /candidate
sha256sum -c - <<EOF
a87bbcec949bc5668a0fdcf14100bf20901a9b9242c3df0627aa3ac4dd74e8ed  qsvdec.c
d0612fbabd19dd9797d17191204d9d57b57789ff00fbab6d638d83f1c8e3350f  qsv_dovi.h
4e526cb591dca24dc5d82830fc24f35a8d3ed87623bd622f7cf2acc0ef172c5f  test_qsv_dovi_mfx.c
9f01aadf2a9be0916bf1eec4dc9d542d24d94694ffeba1d57fa3f3c171765f0b  test_qsv_dovi_config.h
EOF
cc -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror \
 -Wno-unused-parameter -Wno-missing-field-initializers -Wno-sign-compare \
 -Wno-unused-const-variable -ffunction-sections -fdata-sections \
 -I/candidate -I/opt/ffmpeg-source -I/opt/ffmpeg-source/libavcodec -I/usr/include/vpl \
 -include /candidate/test_qsv_dovi_config.h /candidate/test_qsv_dovi_mfx.c \
 /opt/ffmpeg-source/libavcodec/libavcodec.a /opt/ffmpeg-source/libavutil/libavutil.a \
 -Wl,--gc-sections -Wl,--wrap=ff_decode_frame_props -Wl,--wrap=ff_attach_decode_data \
 -Wl,--wrap=ff_get_buffer -lvpl -lva -lva-drm -lm -lpthread -ldl -o /tmp/test
/tmp/test
cc -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror -ffunction-sections -fdata-sections -I/candidate -I/opt/ffmpeg-source -I/opt/ffmpeg-source/libavcodec /candidate/test_qsv_dovi_key.c /opt/ffmpeg-source/libavcodec/libavcodec.a /opt/ffmpeg-source/libavutil/libavutil.a -Wl,--gc-sections -lvpl -lva -lva-drm -lm -lpthread -ldl -o /tmp/key
/tmp/key
peak=$(cat /sys/fs/cgroup/memory.peak)
test "$peak" -gt 0 && test "$peak" -le 536870912
test "$(cat /sys/fs/cgroup/memory.swap.current)" -eq 0
test "$(cat /sys/fs/cgroup/memory.swap.peak)" -eq 0
awk '$2 != 0 {bad=1} END {exit bad}' /sys/fs/cgroup/memory.events
printf "memory_peak=%s\n" "$peak"
cat /sys/fs/cgroup/memory.events
