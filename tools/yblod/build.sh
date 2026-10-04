#!/bin/bash
# Build a libreelec-yblod image in the LibreELEC build container.
#
# Sized for the build host "Ollie" (i9-14900K, 32 threads, 31 GB RAM, about 15 GB of which
# is used by other services). The container is capped at 12 GB with no swap: if the build runs
# out of memory, the compiler inside the container is killed and the host keeps running
# (an uncapped build took the whole host down on 2026-10-01). The build starts with many jobs
# (7: Kodi compilers use 1.0-1.4 GB each with LTO, ~9 GB) and only steps down when it was killed for memory; LibreELEC builds are incremental, so a
# retry resumes where it stopped.
#
# usage: tools/yblod/build.sh <version>        e.g. tools/yblod/build.sh 0.1
# env:   BUILD_IMAGE (default libreelec-dv-build), BUILD_MEMORY (12g), BUILD_JOBS ("7 5 3")
set -u
V=${1:?usage: tools/yblod/build.sh <version>}
T=$(cd "$(dirname "$0")/../.." && pwd)
IMAGE=${BUILD_IMAGE:-libreelec-dv-build}
MEM=${BUILD_MEMORY:-12g}
LOG="$T/build-yblod-$V.log"
for JOBS in ${BUILD_JOBS:-7 5 3}; do
  echo "== $(date '+%F %T') yblod-$V: $JOBS jobs, $MEM memory cap" | tee -a "$LOG"
  docker run --rm --name yblod-build --cpu-shares 256 --memory "$MEM" --memory-swap "$MEM" \
    -v "$T":/build -w /build \
    -e PROJECT=Generic -e DEVICE=Generic -e ARCH=x86_64 \
    -e CONCURRENCY_MAKE_LEVEL="$JOBS" -e THREADCOUNT=4 \
    -e CUSTOM_VERSION="yblod-$V" -e BUILDER_NAME=yblod \
    "$IMAGE" bash -c "make image" >> "$LOG" 2>&1
  rc=$?
  if [ $rc -eq 0 ]; then
    echo "== $(date '+%F %T') done" | tee -a "$LOG"
    ls -l "$T"/target/*yblod-"$V"* 2>/dev/null
    exit 0
  fi
  if ! tail -400 "$LOG" | grep -q -E "Killed|out of memory|signal 9|terminated signal"; then
    echo "== $(date '+%F %T') build failed (exit $rc), not a memory kill; see $LOG" | tee -a "$LOG"
    exit $rc
  fi
  echo "== $(date '+%F %T') ran out of memory at $JOBS jobs, retrying with fewer" | tee -a "$LOG"
done
echo "== out of memory at every job level" | tee -a "$LOG"
exit 1
