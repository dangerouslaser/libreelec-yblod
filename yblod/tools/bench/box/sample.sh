#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
#
# sample.sh OUT SECONDS [REQUEST]: one measurement window on the box (busybox
# sh). It only records raw counters; bench.py turns them into numbers.
#
# At the start (t0) and the end (t1) of the window it saves, under OUT/:
#   tN.time      wall clock (s.ns) before and after the snapshot, and the
#                same instant as Kodi's log writes it
#   tN.fdinfo    "client-id engine ns" for every DRM file kodi.bin holds
#   tN.stat      /proc/PID/stat (the process), tN.tasks (every thread)
#   tN.cpustat   the first line of /proc/stat
#   tN.rapl      RAPL energy counters (name, uJ), when readable
#   tN.temp      thermal zones
#   tN.loglines  the number of lines in kodi.log
# and in between, every 0.5 s, the GPU's actual and requested frequency
# (freq.txt). The kernel trace (trace.txt.gz) holds every page flip event
# delivered to Kodi with its vertical blank sequence number, between the
# markers bench:t0 and bench:t1 that are written at the two snapshots.
#
# REQUEST: a file holding one JSON-RPC request, posted to Kodi after the t0
# snapshot, behind a bench:request marker (playback start timing: the trace
# then shows how long after the request the first pictures were flipped).

set -u

OUT="$1"
SECS="$2"
REQUEST="${3:-}"

TRACE=/sys/kernel/tracing
LOG=/storage/.kodi/temp/kodi.log
RPC_HTTP="http://127.0.0.1:8080/jsonrpc"
RPC_USER="kodi:bench"
EVENTS="drm/drm_vblank_event_delivered drm/drm_vblank_event"

die() {
  echo "sample: $*" >&2
  exit 1
}

PID=$(pidof kodi.bin) || die "kodi.bin is not running"
mkdir -p "${OUT}"
[ -d "${TRACE}/events" ] || mount -t tracefs nodev "${TRACE}" 2>/dev/null
[ -d "${TRACE}/events/drm" ] || die "no DRM trace events in ${TRACE}"

GT=""
for d in /sys/class/drm/card?; do
  [ -r "${d}/gt_act_freq_mhz" ] && GT="${d}"
done
AMD=$(ls /sys/class/drm/card?/device/gpu_busy_percent 2>/dev/null | head -n 1)

events() {
  for e in ${EVENTS}; do
    echo "$1" > "${TRACE}/events/${e}/enable"
  done
}

snapshot() {
  {
    date +%s.%N
    date '+%Y-%m-%d %H:%M:%S'
  } > "${OUT}/$1.time"
  echo "bench:$1" > "${TRACE}/trace_marker"
  # cat, not awk, opens the files: descriptors close while Kodi plays, and
  # busybox awk gives up on the first file that is gone. "pos:" starts a file.
  cat /proc/"${PID}"/fdinfo/* 2>/dev/null |
    awk '/^pos:/ { id = "" }
         /^drm-client-id:/ { id = $2 }
         /^drm-engine-/ { print id, $1, $2 }' > "${OUT}/$1.fdinfo"
  date +%s.%N >> "${OUT}/$1.time"
  cat "/proc/${PID}/stat" > "${OUT}/$1.stat"
  cat /proc/"${PID}"/task/*/stat > "${OUT}/$1.tasks" 2>/dev/null
  head -n 1 /proc/stat > "${OUT}/$1.cpustat"
  for z in /sys/class/powercap/intel-rapl:*; do
    [ -r "${z}/energy_uj" ] &&
      echo "$(cat "${z}/name") $(cat "${z}/energy_uj") $(cat "${z}/max_energy_range_uj")"
  done > "${OUT}/$1.rapl" 2>/dev/null
  for z in /sys/class/thermal/thermal_zone*; do
    [ -r "${z}/temp" ] && echo "$(cat "${z}/type") $(cat "${z}/temp")"
  done > "${OUT}/$1.temp" 2>/dev/null
  wc -l < "${LOG}" > "${OUT}/$1.loglines"
}

# The display and audio state the window ran in.
{
  for c in /sys/class/drm/card?-*; do
    echo "connector ${c##*/} $(cat "${c}/status") $(cat "${c}/enabled")"
  done
  for f in /sys/kernel/debug/dri/*/i915_display_info; do
    if [ -r "${f}" ]; then
      grep -A 12 -E '^\[CRTC' "${f}" |
        grep -E 'CRTC|uapi: enable=yes|adjusted_mode="[^"]|port_clock=[1-9]|uapi: \[FB:[1-9]'
      break
    fi
  done
} > "${OUT}/display.txt" 2>/dev/null
for s in /proc/asound/card*/pcm*p/sub0; do
  if grep -q RUNNING "${s}/status" 2>/dev/null; then
    echo "${s} $(tr '\n' ' ' < "${s}/hw_params")"
  fi
done > "${OUT}/audio.txt"

echo 0 > "${TRACE}/tracing_on"
echo > "${TRACE}/trace"
events 1
echo 1 > "${TRACE}/tracing_on"

snapshot t0
if [ -n "${REQUEST}" ]; then
  echo "bench:request" > "${TRACE}/trace_marker"
  curl -s -m 20 -u "${RPC_USER}" -H 'Content-Type: application/json' -d "@${REQUEST}" \
    "${RPC_HTTP}" > "${OUT}/request.reply"
fi

end=$(($(date +%s%N) + SECS * 1000000000))
: > "${OUT}/freq.txt"
while [ "$(date +%s%N)" -lt "${end}" ]; do
  if [ -n "${GT}" ]; then
    echo "$(date +%s.%N) $(cat "${GT}/gt_act_freq_mhz") $(cat "${GT}/gt_cur_freq_mhz")"
  elif [ -n "${AMD}" ]; then
    echo "$(date +%s.%N) busy $(cat "${AMD}")"
  fi >> "${OUT}/freq.txt"
  sleep 0.5
done

snapshot t1
echo 0 > "${TRACE}/tracing_on"
events 0
# The header keeps the counts that show whether the buffer overflowed.
grep -E '^# entries-in-buffer|tracing_mark_write: bench:|drm_vblank_event' "${TRACE}/trace" |
  gzip > "${OUT}/trace.txt.gz"
echo > "${TRACE}/trace"
echo 1 > "${TRACE}/tracing_on"
