#!/bin/sh
# Actual initialization body and CPU regressions; hardware operations mocked.
set -eu
sdk=${1:?LibreELEC SDK repository required}
candidate=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test -d "$sdk/build.LibreELEC-Generic.x86_64-13.0-devel/build/ffmpeg-9.0.2"
for mode in real_init mfx gate object; do
 image=sha256:33c6601e0e65d900edc712bdb6f40bb1e680669d5ffb76ecd014c8e6f2ec0e1e
 test "$mode" != object || image=sha256:40b586615eae489cab72f139f659b81360da4c9e0b0787fadc5cba0119d9b29e
 docker run --rm --memory=512m --memory-swap=512m --cpus=1 --network=none \
  --read-only --user 0:0 --tmpfs /tmp:rw,nosuid,exec,size=16m \
  -e PYTHONDONTWRITEBYTECODE=1 -e QSV_DOVI_FIXTURE_ROOT=/tmp/qsv-dovi-fixture \
  -e QSV_DOVI_HELPER_ROOT=/candidate \
  -v "$sdk:/build:ro" -v "$candidate:/candidate:ro" \
  --entrypoint /bin/sh "$image" -c '
    set -eu
    test "$(cat /sys/fs/cgroup/memory.max)" -eq 536870912
    test "$(cat /sys/fs/cgroup/memory.swap.max)" -eq 0
    awk '\''$1 == "max" || $1 <= 0 || $2 <= 0 || $1 > $2 {exit 1}'\'' /sys/fs/cgroup/cpu.max
    python3 /candidate/stage_qsv_dovi_real_init_fixture.py
    case "$1" in
      object) python3 /candidate/compile_qsv_dovi_sdk.py ;;
      real_init)
        cc -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror \
          -Wno-unused-parameter -Wno-missing-field-initializers -Wno-sign-compare \
          -Wno-unused-const-variable -ffunction-sections -fdata-sections \
          -I/tmp/qsv-dovi-fixture -I/opt/ffmpeg-source -I/opt/ffmpeg-source/libavcodec \
          -I/usr/include/vpl -include /candidate/test_qsv_dovi_config.h \
          /tmp/qsv-dovi-fixture/test_qsv_dovi_real_init.c \
          /opt/ffmpeg-source/libavcodec/libavcodec.a /opt/ffmpeg-source/libavutil/libavutil.a \
          -Wl,--gc-sections -Wl,--wrap=ff_decode_frame_props \
          -Wl,--wrap=ff_attach_decode_data -Wl,--wrap=ff_get_buffer \
          -lvpl -lva -lva-drm -lm -lpthread -ldl -o /tmp/test
        /tmp/test ;;
      *) sh /candidate/check_qsv_dovi_decoder_cpu.sh "$1" ;;
    esac
    peak=$(cat /sys/fs/cgroup/memory.peak)
    test "$peak" -gt 0 && test "$peak" -le 536870912
    test "$(cat /sys/fs/cgroup/memory.swap.current)" -eq 0
    test "$(cat /sys/fs/cgroup/memory.swap.peak)" -eq 0
    awk '\''$2 != 0 {bad=1} END {exit bad}'\'' /sys/fs/cgroup/memory.events
    printf "memory_peak=%s\n" "$peak"
    cat /sys/fs/cgroup/memory.events' qsv-dovi-cpu "$mode"
done
