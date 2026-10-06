#!/bin/sh
# Build the row-streamed full-frame synthetic transport comparison.
set -eu
if [ "$#" -ne 3 ]; then
  printf 'Usage: %s SDK_ROOT PATCHED_KODI_SOURCE OUTPUT_DIRECTORY\n' "$0" >&2
  exit 2
fi
sdk_root=$1
kodi_source=$2
probe_output=$3
probe_source=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
bridge_source=$kodi_source/tools/dvbridge
test -d "$probe_output"
"$sdk_root/bin/x86_64-libreelec-linux-gnu-gcc" -std=c11 -O2 -fno-lto -Wall -Wextra -Werror \
  -fno-fast-math -ffp-contract=off -I"$bridge_source" \
  "$probe_source/native_planar_packed_probe.c" "$bridge_source/dvbridge_render.c" \
  "$bridge_source/dvbridge_core.c" "$bridge_source/dvbridge_placebo.c" \
  -o "$probe_output/native-planar-packed-probe" \
  -lplacebo -lavutil -lavcodec -lEGL -lGLESv2 -lm
