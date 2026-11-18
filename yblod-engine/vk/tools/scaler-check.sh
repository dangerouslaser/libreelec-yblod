#!/bin/sh
# The FSR 1 upscaler's checks (dvvk_set_scaler, src/scaler.rs), headless on a
# box with the GPU, beside golden.sh (whose pictures are never enlarged: its
# clips are 3840 wide):
#
#   scaler-check.sh [check|update] P81_CLIP YL_CLIP FEL_CLIP [MEL_CLIP]
#
# P81_CLIP (p81-3840x1744-l5full.mkv) and YL_CLIP (28yl-p81.mkv) are made
# 1080p Profile 8.1 sources first (ffmpeg's libx265 carries their RPUs; no
# reference clip is smaller than 3840 wide): P81 as 1920x872 padded to 1080
# rows (its L5 says the whole frame is film), YL at 1920x1080 keeping its
# 4K L5 offsets, so the engine shows rows 384..696 of it: a letterboxed
# source whose bars hold picture the engine reconstructs. Both are enlarged
# into the 3840x2160 canvas; FEL_CLIP and MEL_CLIP (4K) into a 4096x4096
# canvas (dvvk_create_canvas). Then:
#   1. accuracy: each EASU / EASU + RCAS tunnel picture's luma against
#      dvvk-scaler-compare's double-precision CPU reference of the same
#      picture unscaled: no code may differ by more than one.
#   2. invariants: --scaler bilinear gives the bytes of a run that never
#      calls dvvk_set_scaler; switching to FSR mid-stream (--scaler-from)
#      gives the bytes of FSR from the start (damage: the output buffers
#      were last written with the bilinear pack); the overlay stored bottom
#      first (--flip) gives its twin's bytes; an unknown method is refused.
#   3. the pictures' sha256 in scaler.sha256, recorded on the GPU and driver
#      named in its header: strict (a difference fails) when this run's
#      vulkaninfo names the same (SCALER_STRICT=0|1 overrides), else
#      reported only. The made clips' video packets' sha256 are in the file
#      too (not the files': Matroska writes a random segment UID): another
#      ffmpeg or x265 makes other clips, and then the hashes aren't compared.
#      The bilinear pictures' hashes (p81-bl, p81-odd-bl, fel-*-bl) are the
#      engine's from before dvvk_set_scaler existed.
# `update` rewrites scaler.sha256 from this run (checks 1 and 2 must pass;
# SCALER_GPU: the GPU's name for its header, default vulkaninfo's).
#
# BENCH, COMPARE: dvvk-bench, dvvk-scaler-compare (default: next to this
# script, else PATH, else COMPARE is built into WORK). WORK: scratch
# directory (default /tmp/dvvk-scaler; about 70 MB a picture while it is
# checked; the made clips are kept there). GOLDEN: the hash file.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
MODE=check
case ${1:-} in check|update) MODE=$1; shift ;; esac
P81SRC=${1:?usage: scaler-check.sh [check|update] P81_CLIP YL_CLIP FEL_CLIP [MEL_CLIP]}
YLSRC=${2:?YL_CLIP}
FEL=${3:?FEL_CLIP}
MEL=${4:-}
tool() { if [ -x "$HERE/$1" ]; then echo "$HERE/$1"; elif command -v "$1" >/dev/null; then command -v "$1"; fi; }
BENCH=${BENCH:-$(tool dvvk-bench)}
GOLDEN=${GOLDEN:-$HERE/scaler.sha256}
WORK=${WORK:-/tmp/dvvk-scaler}
FRAMES=${FRAMES:-12}
AT=${AT:-0,11}
mkdir -p "$WORK"
COMPARE=${COMPARE:-$(tool dvvk-scaler-compare)}
if [ -z "$COMPARE" ]; then
  COMPARE=$WORK/dvvk-scaler-compare
  cc -O2 -std=gnu11 -ffp-contract=off -o "$COMPARE" "$HERE/dvvk-scaler-compare.c" -lm
fi
size() { wc -c < "$1" | tr -d ' '; }
hash() { sha256sum < "$1" | cut -c1-64; }
vhash() { ffmpeg -v error -i "$1" -map 0:v -c copy -f hash -hash sha256 - | sed 's/^SHA256=//'; }

# The 1080p sources: x265 needs VBV for Dolby Vision's HRD and, for 8.1,
# mastering metadata (the l5full clip has none: BT.2020 1000 nits given).
X265="log-level=error:crf=14:vbv-maxrate=40000:vbv-bufsize=40000:hdr10=1:repeat-headers=1"
X265="$X265:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:chromaloc=2"
MD="master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,50):max-cll=1000,400"
make1080() {
  out=$WORK/$1 src=$2 vf=$3 params=$4
  [ -s "$out" ] && return 0
  ffmpeg -hide_banner -loglevel error -y -i "$src" -an -sn -vf "$vf" -pix_fmt yuv420p10le -c:v libx265 \
    -preset fast -dolbyvision 1 -x265-params "$params" -color_primaries bt2020 -color_trc smpte2084 \
    -colorspace bt2020nc -chroma_sample_location topleft "$out.tmp.mkv"
  mv "$out.tmp.mkv" "$out"
}
make1080 p81-1080.mkv "$P81SRC" scale=1920:872:flags=lanczos,pad=1920:1080:0:104 "$X265:$MD"
make1080 28yl-1080.mkv "$YLSRC" scale=1920:1080:flags=lanczos "$X265"
P81=$WORK/p81-1080.mkv
YL=$WORK/28yl-1080.mkv

OUT=$WORK/run.sha256
: > "$OUT"
{
  echo "# clip p81 $(basename "$P81SRC") $(size "$P81SRC") -> p81-1080.mkv video $(vhash "$P81")"
  echo "# clip yl $(basename "$YLSRC") $(size "$YLSRC") -> 28yl-1080.mkv video $(vhash "$YL")"
  echo "# clip fel $(basename "$FEL") $(size "$FEL")"
  [ -z "$MEL" ] || echo "# clip mel $(basename "$MEL") $(size "$MEL")"
} >> "$OUT"

# golden.sh's overlay at 3840x2160
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

bad=0
# name clip dvvk-bench options...: the pictures at $AT, kept as $WORK/name.N
# until forget
render() {
  name=$1 clip=$2
  shift 2
  rm -f "$WORK/$name".*
  "$BENCH" --frames "$FRAMES" --rate 0 --dump "$WORK/$name" --dump-at "$AT" "$@" "$clip" > "$WORK/$name.log" 2>&1 \
    || { echo "FAIL $name: dvvk-bench exited $?" >&2; cat "$WORK/$name.log" >&2; bad=1; return 0; }
  for f in $(echo "$AT" | tr , ' '); do
    [ -f "$WORK/$name.$f" ] || { echo "FAIL $name: no picture $f" >&2; bad=1; }
  done
}
record() {
  for f in $(echo "$AT" | tr , ' '); do
    [ -f "$WORK/$1.$f" ] && echo "$(hash "$WORK/$1.$f") $1.$f" >> "$OUT"
  done
}
forget() { for n in "$@"; do rm -f "$WORK/$n".[0-9]*; done; }
# name source-name method compare-options...: check 1 on each picture
compare() {
  name=$1 src=$2 method=$3
  shift 3
  for f in $(echo "$AT" | tr , ' '); do
    if line=$("$COMPARE" --method "$method" "$@" "$WORK/$src.$f" "$WORK/$name.$f" 2>&1); then
      echo "$line" | tail -1 | sed "s/^dvvk-scaler-compare:/  $name.$f:/"
    else
      echo "FAIL $name.$f: $line" >&2
      bad=1
    fi
  done
}
# name other: check 2, the same bytes
same() {
  for f in $(echo "$AT" | tr , ' '); do
    if [ "$(hash "$WORK/$1.$f")" != "$(hash "$WORK/$2.$f")" ]; then
      echo "FAIL $1.$f differs from $2.$f" >&2
      bad=1
    fi
  done
}

S="--overlay $OV"
FULL="--source 0,0,1920,1080 --dest 0,0,3840,2160"
# P8.1 at 1080p: unscaled (the reference's source), bilinear, EASU, RCAS
render p81-src "$P81" --dest 0,0,1920,1080
render p81-none "$P81"
render p81-bl "$P81" --scaler bilinear
same p81-bl p81-none
record p81-bl
render p81-easu "$P81" --scaler easu
compare p81-easu p81-src easu $FULL
record p81-easu
render p81-rcas "$P81" --scaler rcas
compare p81-rcas p81-src rcas $FULL
record p81-rcas
# a destination not of whole workgroups, not 2x, not at the origin
render p81-odd "$P81" --scaler rcas --dest 4,2,3836,2156
compare p81-odd p81-src rcas --source 0,0,1920,1080 --dest 4,2,3836,2156
record p81-odd
render p81-odd-bl "$P81" --scaler bilinear --dest 4,2,3836,2156
record p81-odd-bl
forget p81-none p81-bl p81-easu p81-odd p81-odd-bl
# the output modes map what the pack made
render p81-hdr10 "$P81" --scaler rcas --output hdr10
record p81-hdr10
render p81-h10p "$P81" --scaler rcas --output hdr10plus
record p81-h10p
render p81-sdr "$P81" --scaler rcas --output sdr
record p81-sdr
render p81-sdr-static "$P81" --scaler easu --output sdr --mode static $S
record p81-sdr-static
forget p81-hdr10 p81-h10p p81-sdr p81-sdr-static
# the overlays: the fused shell, stored bottom first, prepared; damage
render p81-static "$P81" --scaler rcas --mode static $S
record p81-static
render p81-static-flip "$P81" --scaler rcas --mode static --flip $S
same p81-static-flip p81-static
export DVVK_OVERLAY_PREPARE=1
render p81-prepared "$P81" --scaler rcas --mode static $S
unset DVVK_OVERLAY_PREPARE
record p81-prepared
render p81-rect "$P81" --scaler rcas --mode rect $S
record p81-rect
# from picture 8: pictures 8..11 go to the buffers 4..7 wrote with bilinear
render p81-switch "$P81" --scaler rcas --scaler-from 8 --mode rect $S
for f in $(echo "$AT" | tr , ' '); do
  [ "$f" -ge 8 ] && [ "$(hash "$WORK/p81-switch.$f")" != "$(hash "$WORK/p81-rect.$f")" ] \
    && { echo "FAIL p81-switch.$f differs from p81-rect.$f" >&2; bad=1; }
done
forget p81-static p81-static-flip p81-prepared p81-rect p81-switch p81-src p81-rcas
# an unknown method: refused, nothing rendered
if "$BENCH" --frames 1 --rate 0 --scaler 3 "$P81" > "$WORK/unknown.log" 2>&1 \
  || ! grep -q "dvvk_set_scaler failed" "$WORK/unknown.log"; then
  echo "FAIL --scaler 3: not refused" >&2
  bad=1
fi

# the letterboxed 1080p source (rows 384..696 shown)
render yl-src "$YL" --dest 0,0,1920,1080
for m in easu rcas; do
  render yl-$m "$YL" --scaler $m
  compare yl-$m yl-src $m $FULL
  record yl-$m
  forget yl-$m
done
forget yl-src

# 4K into 4096x4096: the FEL with both EL scalers (FSR takes the staged
# route; the bilinear EL is fused otherwise), 4096x2304 at y 896, and the
# whole canvas (unequal scales)
C4="--canvas 4096,4096"
for el in annexb bilinear; do
  render fel-$el-src "$FEL" --el-scaler $el
  render fel-$el-rcas "$FEL" --el-scaler $el $C4 --scaler rcas
  compare fel-$el-rcas fel-$el-src rcas --source-canvas 3840,2160 --canvas 4096,4096 --source 0,0,3840,2160 \
    --dest 0,896,4096,2304
  record fel-$el-rcas
  render fel-$el-bl "$FEL" --el-scaler $el $C4 --scaler bilinear
  record fel-$el-bl
  forget fel-$el-rcas fel-$el-bl
done
render fel-annexb-easu "$FEL" --el-scaler annexb $C4 --dest 0,0,4096,4096 --scaler easu
compare fel-annexb-easu fel-annexb-src easu --source-canvas 3840,2160 --canvas 4096,4096 --source 0,0,3840,2160 \
  --dest 0,0,4096,4096
record fel-annexb-easu
forget fel-annexb-easu fel-annexb-src fel-bilinear-src
if [ -n "$MEL" ]; then
  render mel-src "$MEL" --el-scaler bilinear
  render mel-rcas "$MEL" --el-scaler bilinear $C4 --dest 0,0,4096,4096 --scaler rcas
  compare mel-rcas mel-src rcas --source-canvas 3840,2160 --canvas 4096,4096 --source 0,0,3840,2160 \
    --dest 0,0,4096,4096
  record mel-rcas
  forget mel-src mel-rcas
fi

n=$(grep -vc '^#' "$OUT")
if [ "$bad" != 0 ]; then
  echo "scaler-check.sh: FAILED"
  exit 1
fi
echo "scaler-check.sh: every luma code within 1 of the CPU reference, invariants hold ($n pictures)"
if [ "$MODE" = update ]; then
  dev=$(vulkaninfo --summary 2>/dev/null | sed -n "s/^[[:space:]]*deviceName *= *//p" | head -1)
  drv=$(vulkaninfo --summary 2>/dev/null | sed -n "s/^[[:space:]]*driverInfo *= *//p" | head -1)
  {
    echo "# FSR 1 upscaler hashes (tools/scaler-check.sh), valid for the GPU and driver they were recorded on:"
    echo "# ${SCALER_GPU:-${dev:-unknown GPU}, Mesa $(echo "$drv" | sed -n 's/^Mesa \([0-9.]*\).*/\1/p')}"
    cat "$OUT"
  } > "$GOLDEN"
  echo "scaler-check.sh: wrote $n hashes to $GOLDEN"
  exit 0
fi
want=$(sed -n 2p "$GOLDEN" | cut -c3-)
dev=$(vulkaninfo --summary 2>/dev/null | sed -n "s/^[[:space:]]*deviceName *= *//p" | head -1)
ver=$(vulkaninfo --summary 2>/dev/null | sed -n "s/^[[:space:]]*driverInfo *= *//p" | head -1 | sed -n 's/^Mesa \([0-9.]*\).*/\1/p')
match=0
case "$want" in "$dev"*", Mesa $ver") [ -n "$dev" ] && [ -n "$ver" ] && match=1 ;; esac
strict=${SCALER_STRICT:-$match}
grep -v '^# ' "$GOLDEN" > "$WORK/golden.cmp" || true
grep -v '^# ' "$OUT" > "$WORK/run.cmp" || true
grep '^# clip' "$GOLDEN" > "$WORK/golden.clips" || true
grep '^# clip' "$OUT" > "$WORK/run.clips" || true
if [ "$(hash "$WORK/golden.clips")" != "$(hash "$WORK/run.clips")" ]; then
  echo "scaler-check.sh: other clips than $GOLDEN was recorded with: hashes not compared"
  [ "$strict" = 0 ] || exit 1
elif [ "$(hash "$WORK/golden.cmp")" = "$(hash "$WORK/run.cmp")" ]; then
  echo "scaler-check.sh: hashes identical ($n)"
else
  grep -vxFf "$WORK/golden.cmp" "$WORK/run.cmp" | sed 's/^/+/' >&2 || true
  d=$(grep -vxFf "$WORK/golden.cmp" "$WORK/run.cmp" | wc -l | tr -d ' ')
  echo "scaler-check.sh: $d of $n hashes differ from $GOLDEN ($want; this run \"$dev\", Mesa $ver)"
  [ "$strict" = 0 ] || exit 1
fi
