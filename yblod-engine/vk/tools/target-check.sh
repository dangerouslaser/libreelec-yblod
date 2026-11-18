#!/bin/sh
# The display-targeted outputs' checks (CroqueMr's CB1 Expert recipe: LLDV
# and HDR10 Rendering Reference; docs/intel-dv/OUTPUT-MODES.md), headless on
# a box with the GPU, as sdr-check.sh checks the SDR output:
#
#   target-check.sh [check|update] FEL_CLIP MEL_CLIP P81_CLIP [P5_CLIP]
#
# For each configuration dvvk-bench renders the same pictures twice, as the
# Dolby Vision tunnel's bytes (the reconstruction, which golden.sh pins) and
# as the display-targeted output, and each output picture is compared with
#   1. the CPU's double-precision map of the tunnel picture (dvvk-map-test
#      --out: HDR10's pairs, or LLDV's pack with its 1-2-1 chroma and the
#      overlay blended in the display's light): no sample may differ by more
#      than one code of the carrier's grid (12-bit codes; one 10-bit code,
#      four 12-bit ones, with --bits 10). This holds on any GPU.
#   2. its sha256 in target.sha256, recorded on the GPU named in that file's
#      header (a different hash with check 1 passing is expected on another
#      GPU: reported, not an error; TARGET_STRICT=1 makes it one).
# and an LLDV overlay stored bottom first (DVVK_OVERLAY_FLIP_Y) must give its
# twin's bytes. `update` rewrites target.sha256 from this run. 3840x2160.
#
# BENCH, MAPTEST, COMPARE: dvvk-bench, dvvk-map-test, dvvk-hdr10-compare
# (default: next to this script, else PATH). WORK: scratch directory (default
# /tmp/dvvk-target). GOLDEN: the hash file. P5_START: seconds into the P5
# clip (default 34.6: the landscape demo's 4000 cd/m2 scene).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
MODE=check
case ${1:-} in check|update) MODE=$1; shift ;; esac
FEL=${1:?usage: target-check.sh [check|update] FEL_CLIP MEL_CLIP P81_CLIP [P5_CLIP]}
MEL=${2:?MEL_CLIP}
P81=${3:?P81_CLIP}
P5=${4:-}
tool() { if [ -x "$HERE/$1" ]; then echo "$HERE/$1"; else echo "$1"; fi; }
BENCH=${BENCH:-$(tool dvvk-bench)}
MAPTEST=${MAPTEST:-$(tool dvvk-map-test)}
COMPARE=${COMPARE:-$(tool dvvk-hdr10-compare)}
GOLDEN=${GOLDEN:-$HERE/target.sha256}
WORK=${WORK:-/tmp/dvvk-target}
FRAMES=${FRAMES:-12}
AT=${AT:-0,11}
mkdir -p "$WORK"

# golden.sh's overlay (sdr-check.sh's at 3840x2160: the same bytes)
OV=$WORK/overlay.bgra
[ -s "$OV" ] || python3 -I - "$OV" <<'PY'
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
        rows.append(bytes(px[:W * 4]))
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
S="--mode static --overlay $OV"

OUT=$WORK/run.sha256
: > "$OUT"
size() { wc -c < "$1" | tr -d ' '; }
echo "# clip fel $(basename "$FEL") $(size "$FEL")" >> "$OUT"
echo "# clip mel $(basename "$MEL") $(size "$MEL")" >> "$OUT"
echo "# clip p81 $(basename "$P81") $(size "$P81")" >> "$OUT"
[ -z "$P5" ] || echo "# clip p5 $(basename "$P5") $(size "$P5")" >> "$OUT"
bad=0
worst=0

# name clip "reconstruction options" "output options" [overlay: tunnel|after]
# The reconstruction options go to both runs, the output options (the
# display; dvvk-bench's and dvvk-map-test's spell the same) to the output
# run and the CPU map. An HDR10 target's overlay is blended before the map,
# as the HDR10 output's is: both runs take it (tunnel). LLDV's comes after
# the map: the output run and the CPU map take it (after).
run() {
  name=$1 clip=$2 recon=$3 out=$4 ov=${5:-}
  dvov= outov= layer=
  case "$ov" in
    tunnel) dvov=$S outov=$S ;;
    after) outov=$S layer="--overlay $OV" ;;
  esac
  step=1
  case "$out" in *"--bits 10"*) step=4 ;; esac
  # shellcheck disable=SC2086
  "$BENCH" --frames "$FRAMES" --rate 0 --dump "$WORK/$name.dv" --dump-at "$AT" --metadata "$WORK/$name.md" \
    --metadata-frames "$FRAMES" $recon $dvov "$clip" > "$WORK/$name.dv.log" 2>&1 \
    || { echo "FAIL $name: the tunnel run exited $?" >&2; bad=1; return 0; }
  # shellcheck disable=SC2086
  "$BENCH" --frames "$FRAMES" --rate 0 --dump "$WORK/$name.out" --dump-at "$AT" $recon $out $outov "$clip" \
    > "$WORK/$name.out.log" 2>&1 || { echo "FAIL $name: the output run exited $?" >&2; bad=1; return 0; }
  for f in $(echo "$AT" | tr , ' '); do
    if [ ! -s "$WORK/$name.out.$f" ] || [ ! -s "$WORK/$name.dv.$f" ]; then
      echo "missing $name.$f" >> "$OUT"
      bad=1
      continue
    fi
    echo "$(sha256sum < "$WORK/$name.out.$f" | cut -c1-64) $name.$f" >> "$OUT"
    # dvvk-bench's --output and --target are the CPU map's too
    # shellcheck disable=SC2086
    "$MAPTEST" $out $layer --samples 1 --frame "$WORK/$name.dv.$f" --out "$WORK/$name.cpu.$f" \
      "$WORK/$name.md.$f.bin" > "$WORK/$name.cpu.$f.log" 2>&1 \
      || { echo "FAIL $name.$f: dvvk-map-test exited $?" >&2; bad=1; continue; }
    # the tunnel picture's first rows carry its metadata packets in the
    # chroma's low bit (24 rows at most)
    r=$("$COMPARE" --rows 24,2160 --ref-format carrier --ref "$WORK/$name.cpu.$f" "$WORK/$name.out.$f") \
      || { echo "FAIL $name.$f: dvvk-hdr10-compare exited $?" >&2; bad=1; continue; }
    m=$(echo "$r" | sed -n 's/.* max \([0-9]*\)\.[0-9] at.*/\1/p' | sort -n | tail -1)
    eq=$(echo "$r" | sed -n 's/.*equal \([0-9.]*\)%.*/\1/p' | sort -n | head -1)
    codes=$((m / step))
    echo "$name.$f: max $codes code(s) of the carrier's grid from the CPU map, at least $eq% of a channel's samples equal"
    [ "$codes" -le 1 ] || { echo "FAIL $name.$f: more than one code from the CPU map" >&2; echo "$r" >&2; bad=1; }
    [ "$codes" -le "$worst" ] || worst=$codes
    for x in "$WORK/$name.dv.$f" "$WORK/$name.out.$f" "$WORK/$name.cpu.$f"; do : > "$x"; done
  done
}

L="--output lldv"
T="--output hdr10 --target"
# LG-class OLED primaries as a version 2 VSVDB codes them, and a projector's
# (version 1): the display's own basis
EDID2="--primaries 0.67578,0.32031,0.25391,0.68359,0.14453,0.05078 --edid-version 2"
EDID1="--primaries 0.66406,0.33203,0.21094,0.71094,0.14844,0.05469 --edid-version 1"
B="--el-scaler bilinear"
# LLDV: scenes above (600) and below (1000) the peak, L2 trims (1917, Gemini
# Man), the display's own primaries, CM4.0 trims (28 Years Later's L8 made to
# a target a display takes), 10 bits, a projector, the GUI, Profile 5
run lldv-fel-600        "$FEL" "--cb1" "$L --peak 600"
run lldv-fel-1000       "$FEL" "--cb1" "$L --peak 1000"
run lldv-fel-bl-600     "$FEL" "$B" "$L --peak 600"
run lldv-p81-600-edid   "$P81" "--cb1" "$L --peak 600 $EDID2"
run lldv-p81-cm4-1000   "$P81" "--cb1 --l8-target 49" "$L --peak 1000"
run lldv-p81-cm4-p3edid "$P81" "--cb1 --l8-target 48" "$L --peak 1000 $EDID2"
run lldv-mel-1000-10bit "$MEL" "--cb1" "$L --peak 1000 --black 0.005 --bits 10"
run lldv-mel-projector  "$MEL" "--cb1" "$L --peak 150 --black 0.05 $EDID1"
run lldv-fel-600-gui    "$FEL" "--cb1" "$L --peak 600" after
[ -z "$P5" ] || run lldv-p5-1000 "$P5" "--cb1 --start ${P5_START:-34.6}" "$L --peak 1000"
# HDR10 Rendering Reference: 1000 cd/m2 P3 (CB1's default gamut), 600 BT.2020
# with an LCD's black, a dim projector in BT.709, the GUI
run hdr10t-fel-1000     "$FEL" "--cb1" "$T --peak 1000"
run hdr10t-p81-600-2020 "$P81" "--cb1" "$T --peak 600 --black 0.005 --gamut 2020"
run hdr10t-mel-proj-709 "$MEL" "--cb1" "$T --peak 100 --black 0.05 --gamut 709"
run hdr10t-fel-600-gui  "$FEL" "--cb1" "$T --peak 600" tunnel

# DVVK_OVERLAY_FLIP_Y: the overlay stored bottom first gives its twin's bytes
twin() {
  name=$1 clip=$2
  shift 2
  "$BENCH" --frames "$FRAMES" --rate 0 --dump "$WORK/$name.flip" --dump-at "$AT" --flip "$@" "$clip" \
    > "$WORK/$name.flip.log" 2>&1 || { echo "FAIL $name~flip: dvvk-bench exited $?" >&2; bad=1; return 0; }
  for f in $(echo "$AT" | tr , ' '); do
    h=$(sha256sum < "$WORK/$name.flip.$f" | cut -c1-64)
    : > "$WORK/$name.flip.$f"
    if ! grep -q "^$h $name.$f\$" "$OUT"; then
      echo "target-check.sh: FLIP_Y $name.$f differs from its twin" >&2
      bad=1
    fi
  done
}
# shellcheck disable=SC2086
twin lldv-fel-600-gui "$FEL" --cb1 $L --peak 600 $S

n=$(grep -vc '^#' "$OUT")
# `update` records the hashes whatever check 1 found (they pin this GPU's
# bytes, not their accuracy), and still fails on it
if [ "$MODE" = update ]; then
  {
    echo "# Display-targeted output hashes (tools/target-check.sh), valid for the GPU and driver they were recorded on:"
    echo "# ${TARGET_GPU:-unknown GPU}"
    cat "$OUT"
  } > "$GOLDEN"
  echo "target-check.sh: wrote $n hashes to $GOLDEN"
fi
if [ "$bad" != 0 ]; then
  echo "target-check.sh: FAILED"
  exit 1
fi
echo "target-check.sh: every sample within $worst code(s) of the CPU map ($n pictures), FLIP_Y twin identical"
[ "$MODE" = update ] && exit 0
if [ ! -s "$GOLDEN" ]; then
  echo "target-check.sh: no $GOLDEN to compare hashes with"
  exit 0
fi
grep -v '^# ' "$GOLDEN" > "$WORK/golden.cmp" || true
grep -v '^# ' "$OUT" > "$WORK/run.cmp" || true
grep '^# clip' "$GOLDEN" > "$WORK/golden.clips" || true
grep '^# clip' "$OUT" > "$WORK/run.clips" || true
if [ "$(sha256sum < "$WORK/golden.clips")" != "$(sha256sum < "$WORK/run.clips")" ]; then
  echo "target-check.sh: other clips than $GOLDEN was recorded with: hashes not compared"
elif [ "$(sha256sum < "$WORK/golden.cmp")" = "$(sha256sum < "$WORK/run.cmp")" ]; then
  echo "target-check.sh: hashes identical ($n)"
else
  d=$(grep -vxFf "$WORK/golden.cmp" "$WORK/run.cmp" | wc -l | tr -d ' ')
  echo "target-check.sh: $d of $n hashes differ from $GOLDEN ($(sed -n 2p "$GOLDEN" | cut -c3-)): expected on another GPU or driver"
  [ "${TARGET_STRICT:-0}" = 0 ] || exit 1
fi
