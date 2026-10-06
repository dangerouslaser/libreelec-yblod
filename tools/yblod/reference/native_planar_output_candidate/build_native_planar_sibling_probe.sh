#!/bin/sh
# Compile against the same SDK and canonical bridge used by the candidate.
set -eu
test "$#" = 3
sdk=$1
engine=$2
output=$3
test -d "$output"
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$sdk/bin/x86_64-libreelec-linux-gnu-gcc" -std=c11 -O2 -fno-lto \
  -Wall -Wextra -Werror -I"$engine/experimental" \
  "$source_dir/native_planar_sibling_probe.c" \
  "$engine/experimental/native_egl_output_bridge.c" \
  -o "$output/native-planar-sibling-probe" -lEGL -lGLESv2
sha256sum "$output/native-planar-sibling-probe"
