#!/bin/sh
# Source-only CPU fixtures. The authoritative SDK is mounted read-only.
set -eu
sdk=${1:?LibreELEC SDK repository required}
candidate=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test -d "$sdk/build.LibreELEC-Generic.x86_64-13.0-devel/build/ffmpeg-9.0.2"
for mode in mfx allocator gate object configure; do
 image=yblod-ffmpeg9-decode:9.0.2
 test "$mode" != object || image=libreelec-dv-build:latest
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
    python3 /candidate/stage_qsv_dovi_decoder_fixture.py
    if test "$1" = object || test "$1" = configure; then
      if test "$1" = configure; then
        python3 /candidate/check_qsv_dovi_configure.py
      else
      python3 /candidate/compile_qsv_dovi_sdk.py
      fi
      peak=$(cat /sys/fs/cgroup/memory.peak)
      test "$peak" -gt 0 && test "$peak" -le 536870912
      test "$(cat /sys/fs/cgroup/memory.swap.current)" -eq 0
      test "$(cat /sys/fs/cgroup/memory.swap.peak)" -eq 0
      awk '\''$2 != 0 {bad=1} END {exit bad}'\'' /sys/fs/cgroup/memory.events
      printf "memory_peak=%s\n" "$(cat /sys/fs/cgroup/memory.peak)"
      cat /sys/fs/cgroup/memory.events
    else
      sh /candidate/check_qsv_dovi_decoder_cpu.sh "$1"
    fi' qsv-dovi-cpu "$mode"
done
