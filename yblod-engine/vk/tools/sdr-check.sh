#!/bin/sh
# SDR output's checks (docs/intel-dv/OUTPUT-MODES.md), headless on a box with
# the GPU, beside golden.sh (which stays the oracle of the other outputs):
#
#   sdr-check.sh [check|update] FEL_CLIP [MEL_CLIP [P81_CLIP [P5_CLIP]]]
#
# For each configuration dvvk-bench renders the same pictures twice, as the
# Dolby Vision tunnel's bytes (the Master Reference reconstruction, which
# golden.sh pins) and as SDR, and each SDR picture is compared with
#   1. the CPU's double-precision map of the tunnel picture (dvvk-map-test
#      --out, the overlay blended as the pack blends it): no sample may
#      differ by more than one 8-bit code. This holds on any GPU.
#   2. its sha256 in sdr.sha256, recorded on the GPU named in that file's
#      header. Float arithmetic differs between GPU makes by a code here and
#      there, so on another GPU a different hash with check 1 passing is
#      expected (reported, not an error; SDR_STRICT=1 makes it one).
# and the overlay stored bottom first (DVVK_OVERLAY_FLIP_Y) must give its
# twin's bytes. `update` rewrites sdr.sha256 from this run.
#
# BENCH, MAPTEST, COMPARE: dvvk-bench, dvvk-map-test, dvvk-sdr-compare
# (default: next to this script, else PATH). WORK: scratch directory (default
# /tmp/dvvk-sdr; about 100 MB a picture while it is checked). GOLDEN: the hash
# file. P5_START: seconds into the P5 clip (default 34.6: the Dolby Vision
# landscape demo's 4000 cd/m2 scene).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
MODE=check
case ${1:-} in check|update) MODE=$1; shift ;; esac
FEL=${1:?usage: sdr-check.sh [check|update] FEL_CLIP [MEL_CLIP [P81_CLIP [P5_CLIP]]]}
MEL=${2:-}
P81=${3:-}
P5=${4:-}
tool() { if [ -x "$HERE/$1" ]; then echo "$HERE/$1"; else echo "$1"; fi; }
BENCH=${BENCH:-$(tool dvvk-bench)}
MAPTEST=${MAPTEST:-$(tool dvvk-map-test)}
COMPARE=${COMPARE:-$(tool dvvk-sdr-compare)}
GOLDEN=${GOLDEN:-$HERE/sdr.sha256}
WORK=${WORK:-/tmp/dvvk-sdr}
FRAMES=${FRAMES:-12}
AT=${AT:-0,11}
mkdir -p "$WORK"

# golden.sh's overlay: a bottom bar with a soft top edge, a clock box, a dim strip
OV=$WORK/overlay.bgra
if [ ! -s "$OV" ]; then
  python3 -I - "$OV" <<'PY'
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
PY
fi

OUT=$WORK/run.sha256
: > "$OUT"
size() { wc -c < "$1" | tr -d ' '; }
echo "# clip fel $(basename "$FEL") $(size "$FEL")" >> "$OUT"
[ -z "$MEL" ] || echo "# clip mel $(basename "$MEL") $(size "$MEL")" >> "$OUT"
[ -z "$P81" ] || echo "# clip p81 $(basename "$P81") $(size "$P81")" >> "$OUT"
[ -z "$P5" ] || echo "# clip p5 $(basename "$P5") $(size "$P5")" >> "$OUT"
bad=0
worst=0

# name clip "reconstruction options" "sdr options" "map-test options" [overlay options]
# The reconstruction options are the tunnel run's and the SDR run's; the SDR
# options the display (dvvk-bench's and dvvk-map-test's spell the same); the
# overlay options go to the SDR run only (the tunnel run is the film alone).
run() {
  name=$1 clip=$2 recon=$3 sdr=$4 cpu=$5 ov=${6:-}
  for f in $(echo "$AT" | tr , ' '); do
    for x in dv sdr cpu md.$f.bin md.txt; do : > "$WORK/$name.$f.$x"; done
  done
  # shellcheck disable=SC2086
  "$BENCH" --frames "$FRAMES" --rate 0 --dump "$WORK/$name.dv" --dump-at "$AT" --metadata "$WORK/$name.md" \
    --metadata-frames "$FRAMES" $recon "$clip" > "$WORK/$name.dv.log" 2>&1 \
    || { echo "FAIL $name: the tunnel run exited $?" >&2; bad=1; return 0; }
  # shellcheck disable=SC2086
  "$BENCH" --frames "$FRAMES" --rate 0 --dump "$WORK/$name.sdr" --dump-at "$AT" --output sdr $recon $sdr $ov "$clip" \
    > "$WORK/$name.sdr.log" 2>&1 || { echo "FAIL $name: the SDR run exited $?" >&2; bad=1; return 0; }
  for f in $(echo "$AT" | tr , ' '); do
    if [ ! -s "$WORK/$name.sdr.$f" ] || [ ! -s "$WORK/$name.dv.$f" ]; then
      echo "missing $name.$f" >> "$OUT"
      bad=1
      continue
    fi
    echo "$(sha256sum < "$WORK/$name.sdr.$f" | cut -c1-64) $name.$f" >> "$OUT"
    layer=
    case "$ov" in *--overlay*) layer="--overlay $OV" ;; esac
    # shellcheck disable=SC2086
    "$MAPTEST" --output sdr $cpu $layer --samples 1 --frame "$WORK/$name.dv.$f" --out "$WORK/$name.cpu.$f" \
      "$WORK/$name.md.$f.bin" > "$WORK/$name.cpu.$f.log" 2>&1 \
      || { echo "FAIL $name.$f: dvvk-map-test exited $?" >&2; bad=1; continue; }
    # the tunnel picture's first rows carry its metadata packets in the chroma's low bit
    r=$("$COMPARE" --rows 8,2160 --ref "$WORK/$name.cpu.$f" "$WORK/$name.sdr.$f") \
      || { echo "FAIL $name.$f: dvvk-sdr-compare exited $?" >&2; bad=1; continue; }
    m=$(echo "$r" | sed -n 's/.*max \([0-9]*\) at.*/\1/p' | sort -n | tail -1)
    eq=$(echo "$r" | sed -n 's/.*equal \([0-9.]*\)%.*/\1/p' | sort -n | head -1)
    echo "$name.$f: max $m code(s) from the CPU map, at least $eq% of a channel's samples equal"
    [ "$m" -le 1 ] || { echo "FAIL $name.$f: more than one code from the CPU map" >&2; echo "$r" >&2; bad=1; }
    [ "$m" -le "$worst" ] || worst=$m
    for x in dv sdr cpu md.$f.bin; do : > "$WORK/$name.$f.$x"; done
    for x in "$WORK/$name.dv.$f" "$WORK/$name.sdr.$f" "$WORK/$name.cpu.$f"; do : > "$x"; done
  done
}

S="--mode static --overlay $OV"
B="--el-scaler bilinear"
run fel-cb1           "$FEL" "--cb1" "" ""
run fel-bl            "$FEL" "$B" "" ""
run fel-off           "$FEL" "--fel 0" "" ""
run fel-cb1-100       "$FEL" "--cb1" "--white 100" "--white 100"
run fel-cb1-g22       "$FEL" "--cb1" "--gamma22" "--gamma22"
run fel-cb1-limited   "$FEL" "--cb1" "--limited" "--limited"
run fel-cb1-nodither  "$FEL" "--cb1" "--no-dither" "--no-dither"
run fel-cb1-static    "$FEL" "--cb1" "" "" "$S"
run fel-bl-static     "$FEL" "$B" "" "" "$S"
run fel-cb1-lim-static "$FEL" "--cb1" "--limited" "--limited" "$S"
run fel-box           "$FEL" "$B --dest 960,540,1920,1080" "" ""
if [ -n "$MEL" ]; then
  run mel-cb1         "$MEL" "--cb1" "" ""
  run mel-cb1-100     "$MEL" "--cb1" "--white 100" "--white 100"
  run mel-cb1-static  "$MEL" "--cb1" "" "" "$S"
fi
if [ -n "$P81" ]; then
  run p81-cb1         "$P81" "--cb1" "" ""
  run p81-cb1-100     "$P81" "--cb1" "--white 100" "--white 100"
  run p81-box         "$P81" "$B --dest 960,540,1920,1080" "" ""
fi
if [ -n "$P5" ]; then
  P=${P5_START:-34.6}
  run p5-cb1          "$P5" "--cb1 --start $P" "" ""
  run p5-cb1-100      "$P5" "--cb1 --start $P" "--white 100" "--white 100"
fi

# DVVK_OVERLAY_FLIP_Y: the overlay stored bottom first gives its twin's bytes
twin() {
  name=$1 clip=$2
  shift 2
  "$BENCH" --frames "$FRAMES" --rate 0 --dump "$WORK/$name.flip" --dump-at "$AT" --output sdr --flip "$@" "$clip" \
    > "$WORK/$name.flip.log" 2>&1 || { echo "FAIL $name~flip: dvvk-bench exited $?" >&2; bad=1; return 0; }
  for f in $(echo "$AT" | tr , ' '); do
    h=$(sha256sum < "$WORK/$name.flip.$f" | cut -c1-64)
    : > "$WORK/$name.flip.$f"
    if ! grep -q "^$h $name.$f\$" "$OUT"; then
      echo "sdr-check.sh: FLIP_Y $name.$f differs from its twin" >&2
      bad=1
    fi
  done
}
# shellcheck disable=SC2086
twin fel-cb1-static "$FEL" --cb1 $S
# shellcheck disable=SC2086
twin fel-bl-static "$FEL" $B $S

n=$(grep -vc '^#' "$OUT")
if [ "$bad" != 0 ]; then
  echo "sdr-check.sh: FAILED"
  exit 1
fi
echo "sdr-check.sh: every sample within $worst code(s) of the CPU map ($n pictures), FLIP_Y twins identical"
if [ "$MODE" = update ]; then
  {
    echo "# SDR output hashes (tools/sdr-check.sh), valid for the GPU and driver they were recorded on:"
    echo "# ${SDR_GPU:-unknown GPU}"
    cat "$OUT"
  } > "$GOLDEN"
  echo "sdr-check.sh: wrote $n hashes to $GOLDEN"
  exit 0
fi
if [ ! -s "$GOLDEN" ]; then
  echo "sdr-check.sh: no $GOLDEN to compare hashes with"
  exit 0
fi
grep -v '^# ' "$GOLDEN" > "$WORK/golden.cmp" || true
grep -v '^# ' "$OUT" > "$WORK/run.cmp" || true
grep '^# clip' "$GOLDEN" > "$WORK/golden.clips" || true
grep '^# clip' "$OUT" > "$WORK/run.clips" || true
if [ "$(sha256sum < "$WORK/golden.clips")" != "$(sha256sum < "$WORK/run.clips")" ]; then
  echo "sdr-check.sh: other clips than $GOLDEN was recorded with: hashes not compared"
elif [ "$(sha256sum < "$WORK/golden.cmp")" = "$(sha256sum < "$WORK/run.cmp")" ]; then
  echo "sdr-check.sh: hashes identical ($n)"
else
  d=$(grep -vxFf "$WORK/golden.cmp" "$WORK/run.cmp" | wc -l | tr -d ' ')
  echo "sdr-check.sh: $d of $n hashes differ from $GOLDEN ($(sed -n 2p "$GOLDEN" | cut -c3-)): expected on another GPU or driver"
  [ "${SDR_STRICT:-0}" = 0 ] || exit 1
fi
