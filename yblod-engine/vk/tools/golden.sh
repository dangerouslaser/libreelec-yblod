#!/bin/sh
# Golden output hashes of dv-engine-vk: the oracle for behaviour-preserving
# engine changes (it replaced regress.sh, whose OpenCL comparison went with OpenCL).
# Headless, on a box with the GPU (the N150): dvvk-bench renders a few
# pictures per configuration, dumps some, and their sha256 are compared with
# tools/golden.sha256 (hashes only, no image data in git).
#
#   golden.sh [check|update|profile] FEL_CLIP [MEL_CLIP [P81_CLIP]]
#
#   check    (default) render, hash, compare with golden.sha256; exit 1 on a
#            difference or a missing hash
#   update   write golden.sha256 from this run (only from a known-good engine)
#   profile  DVVK_PROFILE=1 timings, 240 pictures at 23.976 Hz, CB1 contract,
#            no overlay / static overlay / rect overlay (no hashes)
#
# BENCH: dvvk-bench (default: next to this script, else PATH); the engine is
# whatever libdv_engine_vk.so dvvk-bench loads (LD_LIBRARY_PATH for a dev
# build). WORK: scratch directory (default /tmp/dvvk-golden; ~33 MB a dump,
# deleted once hashed). GOLDEN: the hash file (default next to this script).
# The configurations name the clip by role (fel, mel), so the hashes belong
# to the clips they were made with: golden.sha256 records their names and sizes.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
MODE=check
case ${1:-} in check|update|profile) MODE=$1; shift ;; esac
FEL=${1:?usage: golden.sh [check|update|profile] FEL_CLIP [MEL_CLIP]}
MEL=${2:-}
P81=${3:-}
BENCH=${BENCH:-$HERE/dvvk-bench}
[ -x "$BENCH" ] || BENCH=dvvk-bench
GOLDEN=${GOLDEN:-$HERE/golden.sha256}
WORK=${WORK:-/tmp/dvvk-golden}
FRAMES=${FRAMES:-12}
AT=${AT:-0,5,11}
mkdir -p "$WORK"

# The overlay: raw 3840x2160 BGRA premultiplied, deterministic. A bottom bar
# (controls) with a soft top edge, a clock box top right and a translucent
# full-width dim strip: the OSD shapes the CB1 bounds and damage paths see.
OV=$WORK/overlay.bgra
if [ ! -s "$OV" ]; then
  python3 -I - "$OV" <<'EOF'
import sys
W, H = 3840, 2160
rows = []
clear = bytes(W * 4)
for y in range(H):
    if 1700 <= y < 2000:
        a = min(255, (y - 1700) * 4)
        px = bytearray()
        for x in range(0, W, 16):
            c = (x * 255 // W) * a // 255
            px += bytes((c, a // 2, (a * 3) // 4, a)) * 16
        rows.append(bytes(px))
    elif 100 <= y < 220:
        row = bytearray(clear)
        row[3300 * 4:3700 * 4] = bytes((200, 200, 200, 230)) * 400
        rows.append(bytes(row))
    elif 900 <= y < 960:
        rows.append(bytes((10, 10, 10, 96)) * W)
    else:
        rows.append(clear)
open(sys.argv[1], 'wb').write(b''.join(rows))
EOF
fi

if [ "$MODE" = profile ]; then
  for m in none static rect; do
    printf '%s: ' "$m"
    DVVK_PROFILE=1 "$BENCH" --frames 240 --cb1 --mode $m --overlay "$OV" "$FEL" 2>&1 \
      | grep -E '^dvvk profile: gpu' | tail -1
  done
  exit 0
fi

OUT=$WORK/run.sha256
: > "$OUT"
size() { wc -c < "$1" | tr -d ' '; }   # busybox (LibreELEC) has no stat -c
echo "# clip fel $(basename "$FEL") $(size "$FEL")" >> "$OUT"
[ -z "$MEL" ] || echo "# clip mel $(basename "$MEL") $(size "$MEL")" >> "$OUT"
[ -z "$P81" ] || echo "# clip p81 $(basename "$P81") $(size "$P81")" >> "$OUT"

# name clip dvvk-bench options...
run() {
  name=$1 clip=$2
  shift 2
  rm -f "$WORK/$name".*
  "$BENCH" --frames "$FRAMES" --rate 0 --dump "$WORK/$name" --dump-at "$AT" "$@" "$clip" >"$WORK/$name.log" 2>&1 \
    || { echo "FAIL $name: dvvk-bench exited $?" >&2; cat "$WORK/$name.log" >&2; return 1; }
  for f in $(echo "$AT" | tr , ' '); do
    if [ -f "$WORK/$name.$f" ]; then
      echo "$(sha256sum < "$WORK/$name.$f" | cut -c1-64) $name.$f" >> "$OUT"
      rm -f "$WORK/$name.$f"
    else
      echo "missing $name.$f" >> "$OUT"
    fi
  done
}

S="--overlay $OV"
run fel-s0            "$FEL" --el-scaler 0
run fel-s1            "$FEL" --el-scaler 1
run fel-off           "$FEL" --fel 0
run fel-s0-static     "$FEL" --el-scaler 0 --mode static $S
run fel-s0-rect       "$FEL" --el-scaler 0 --mode rect $S
run fel-s1-change     "$FEL" --el-scaler 1 --mode change $S
run fel-cb1           "$FEL" --cb1
run fel-cb1-static    "$FEL" --cb1 --mode static $S
run fel-cb1-rect      "$FEL" --cb1 --mode rect $S
run fel-cb1-change    "$FEL" --cb1 --mode change $S
run fel-box           "$FEL" --dest 960,540,1920,1080
run fel-box-fel       "$FEL" --dest 480,270,2880,1620 --mode static $S
run fel-desktop       "$FEL" --desktop --dest 960,540,1920,1080 --mode rect $S
run fel-fp16          "$FEL" --mode static --fp16 $S
# CM4 metadata (dvvk_plan_in.dm_options, 0.1.0-18): only the packet rows differ
run fel-cb1-cm4       "$FEL" --cb1 --cm4 always
run fel-cb1-nol2      "$FEL" --cb1 --no-l2
run fel-cm4-nol2      "$FEL" --cm4 always --no-l2
if [ -n "$MEL" ]; then
  run mel             "$MEL"
  run mel-static      "$MEL" --mode static $S
  run mel-cb1         "$MEL" --cb1
  run mel-cb1-static  "$MEL" --cb1 --mode static $S
  run mel-cb1-rect    "$MEL" --cb1 --mode rect $S
  run mel-box         "$MEL" --dest 960,540,1920,1080 --mode static $S
  run mel-cb1-cm4     "$MEL" --cb1 --cm4 always
  run mel-cb1-cm4-nol2 "$MEL" --cb1 --cm4 always --no-l2
fi
if [ -n "$P81" ]; then
  run p81             "$P81"
  run p81-cb1-static  "$P81" --cb1 --mode static $S
  run p81-cb1-rect    "$P81" --cb1 --mode rect $S
  run p81-box         "$P81" --dest 960,540,1920,1080 --mode rect $S
  run p81-cb1-cm4     "$P81" --cb1 --cm4 always
fi

# DVVK_OVERLAY_FLIP_Y (Kodi's GUI framebuffer, rows bottom first): the same
# overlay stored upside down must give its twin's bytes. Checked against the
# twin in this run, not recorded in golden.sha256.
MAIN=$OUT
OUT=$WORK/twins.sha256
: > "$OUT"
run fel-s0-static~flip    "$FEL" --el-scaler 0 --mode static --flip $S
run fel-s1-change~flip    "$FEL" --el-scaler 1 --mode change --flip $S
run fel-cb1-static~flip   "$FEL" --cb1 --mode static --flip $S
run fel-cb1-change~flip   "$FEL" --cb1 --mode change --flip $S
run fel-box-fel~flip      "$FEL" --dest 480,270,2880,1620 --mode static --flip $S
[ -z "$MEL" ] || run mel-cb1-static~flip "$MEL" --cb1 --mode static --flip $S
TWINS=$OUT
OUT=$MAIN
twins_bad=0
while read -r hash name; do
  twin=$(echo "$name" | sed 's/~flip//')
  if ! grep -q "^$hash $twin\$" "$OUT"; then
    echo "golden.sh: FLIP_Y $name differs from $twin" >&2
    twins_bad=1
  fi
done < "$TWINS"
[ "$twins_bad" = 0 ] && echo "golden.sh: FLIP_Y twins identical ($(wc -l < "$TWINS") hashes)"

if [ "$MODE" = update ]; then
  [ "$twins_bad" = 0 ] || { echo "golden.sh: not updating (FLIP_Y twins differ)"; exit 1; }
  cp "$OUT" "$GOLDEN"
  echo "golden.sh: wrote $(grep -vc '^#' "$GOLDEN") hashes to $GOLDEN"
  exit 0
fi
# busybox (LibreELEC) has no diff: the lines only one side has
differ() {
  if command -v diff >/dev/null; then
    diff -u "$1" "$2"
  else
    grep -vxFf "$2" "$1" | sed 's/^/-/'
    grep -vxFf "$1" "$2" | sed 's/^/+/'
    [ "$(sha256sum < "$1")" = "$(sha256sum < "$2")" ]
  fi
}
if differ "$GOLDEN" "$OUT" && [ "$twins_bad" = 0 ]; then
  echo "golden.sh: identical ($(grep -vc '^#' "$OUT") hashes)"
elif [ "$twins_bad" != 0 ]; then
  echo "golden.sh: FLIP_Y twins DIFFERENT"
  exit 1
else
  echo "golden.sh: DIFFERENT (above: - golden, + this run)"
  exit 1
fi
