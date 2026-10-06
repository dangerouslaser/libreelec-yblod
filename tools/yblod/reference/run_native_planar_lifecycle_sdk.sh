#!/bin/sh
# Run inside the LibreELEC SDK image, without GPU devices:
# docker run --rm --memory=512m --memory-swap=512m --cpus=1 --network=none \
#   -v "$REPO_PATH":/repo -v "$BUILD_PATH":/build libreelec-dv-build:latest \
#   sh /repo/tools/yblod/reference/run_native_planar_lifecycle_sdk.sh
set -eu
task_reference_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_repo_dir=$(CDPATH= cd -- "$task_reference_dir/../../.." && pwd)
task_toolchain=${YB_SDK_TOOLCHAIN:-/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain}
task_sysroot=${YB_SDK_SYSROOT:-$task_toolchain/x86_64-libreelec-linux-gnu/sysroot}
task_cc=$task_toolchain/bin/x86_64-libreelec-linux-gnu-gcc
task_runtime=$task_sysroot/usr/lib
task_engine=$task_repo_dir/engine
task_memory_limit=$(sed -n '1p' /sys/fs/cgroup/memory.max)
task_swap_limit=$(sed -n '1p' /sys/fs/cgroup/memory.swap.max)
if [ "$task_memory_limit" != 536870912 ] || [ "$task_swap_limit" != 0 ]; then
  printf '%s\n' 'Requires a 512 MiB cgroup memory limit and zero swap.' >&2
  exit 1
fi
if ! awk '{exit !($1 != "max" && $1 > 0 && $2 > 0 && $1 <= $2)}' /sys/fs/cgroup/cpu.max; then
  printf '%s\n' 'Requires a cgroup CPU quota of at most one core.' >&2
  exit 1
fi
if [ ! -x "$task_cc" ] || [ ! -x "$task_runtime/ld-linux-x86-64.so.2" ]; then
  printf '%s\n' 'Set YB_SDK_TOOLCHAIN and optionally YB_SDK_SYSROOT to the SDK locations.' >&2
  exit 1
fi
task_output=$(mktemp -d /tmp/yblod-planar-lifecycle.XXXXXX)
"$task_cc" --sysroot="$task_sysroot" -std=c11 -O2 -fno-lto \
  -Wall -Wextra -Werror -Wconversion -Wshadow -UNDEBUG \
  -ffunction-sections -fdata-sections -Wl,--gc-sections \
  -I"$task_engine/experimental" -I"$task_engine/include" \
  "$task_reference_dir/native_planar_release_probe.c" -o "$task_output/release"
"$task_runtime/ld-linux-x86-64.so.2" --library-path "$task_runtime" "$task_output/release"
"$task_cc" --sysroot="$task_sysroot" -std=c11 -O2 -fno-lto \
  -Wall -Wextra -Werror -Wconversion -Wshadow -UNDEBUG \
  -DYB_EGL_BRIDGE_HOST_ONLY -I"$task_engine/experimental" \
  "$task_reference_dir/native_planar_bridge_ownership_probe.c" \
  "$task_engine/experimental/native_egl_output_bridge.c" -o "$task_output/bridge"
"$task_runtime/ld-linux-x86-64.so.2" --library-path "$task_runtime" "$task_output/bridge"
printf 'Diagnostic binaries retained at %s\n' "$task_output"
for task_field in memory.peak memory.events memory.swap.current; do
  printf '%s: ' "$task_field"
  sed -n '1,20p' "/sys/fs/cgroup/$task_field"
done
