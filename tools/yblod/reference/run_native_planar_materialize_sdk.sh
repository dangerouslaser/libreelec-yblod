#!/bin/sh
# CPU-only actual-context fault probe; run in the SDK image, no GPU devices.
set -eu
reference=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$reference/../../.." && pwd)
sdk=${YB_SDK_TOOLCHAIN:-/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain}
sysroot=${YB_SDK_SYSROOT:-$sdk/x86_64-libreelec-linux-gnu/sysroot}
test "$(sed -n '1p' /sys/fs/cgroup/memory.max)" = 536870912
test "$(sed -n '1p' /sys/fs/cgroup/memory.swap.max)" = 0
awk '{exit !($1!="max" && $1>0 && $2>0 && $1<=$2)}' /sys/fs/cgroup/cpu.max
output=$(mktemp -d /tmp/yblod-planar-materialize.XXXXXX)
"$sdk/bin/x86_64-libreelec-linux-gnu-gcc" --sysroot="$sysroot" \
  -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow -UNDEBUG \
  -ffunction-sections -fdata-sections -Wl,--gc-sections \
  -I"$repo/engine/experimental" -I"$repo/engine/include" \
  "$reference/native_planar_materialize_probe.c" -o "$output/probe"
"$sysroot/usr/lib/ld-linux-x86-64.so.2" --library-path "$sysroot/usr/lib" "$output/probe"
for field in memory.peak memory.events memory.swap.current; do
  printf '%s\n' "$field"
  sed -n '1,20p' "/sys/fs/cgroup/$field"
done
test "$(sed -n '1p' /sys/fs/cgroup/memory.swap.current)" = 0
awk '$2!=0 {exit 1}' /sys/fs/cgroup/memory.events
