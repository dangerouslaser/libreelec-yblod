#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
#
# ktrace.sh OUT SECONDS: a kernel trace of the GPU's requests and the page
# flips for a few seconds of playback (busybox sh), gzipped into OUT. For
# the question "why was this flip late": every request with its engine
# (i915_request_add: class 0 render, 2 video) and context, its completion
# (dma_fence_signaled), the flips delivered to Kodi and, with queued flips,
# their out-fences (timeline "CRTC"). Timestamps are CLOCK_MONOTONIC, as in
# the engine's deadline trace and Kodi's flip trace. Not for a measured
# window: it replaces the tracer's buffer and clock while it runs.

set -u

OUT="$1"
SECS="$2"

TRACE=/sys/kernel/tracing
EVENTS="i915/i915_request_add i915/i915_request_queue i915/i915_request_retire
        dma_fence/dma_fence_emit dma_fence/dma_fence_signaled
        drm/drm_vblank_event_delivered drm/drm_vblank_event"

[ -d "${TRACE}/events" ] || mount -t tracefs nodev "${TRACE}" 2>/dev/null
[ -d "${TRACE}/events/i915" ] || { echo "ktrace: no i915 trace events" >&2; exit 1; }

events() {
  for e in ${EVENTS}; do
    echo "$1" > "${TRACE}/events/${e}/enable"
  done
}

size=$(cat "${TRACE}/buffer_size_kb")
echo 0 > "${TRACE}/tracing_on"
echo > "${TRACE}/trace"
echo 16384 > "${TRACE}/buffer_size_kb"
echo mono > "${TRACE}/trace_clock"
events 1
echo 1 > "${TRACE}/tracing_on"
sleep "${SECS}"
echo 0 > "${TRACE}/tracing_on"
events 0
gzip < "${TRACE}/trace" > "${OUT}"
echo > "${TRACE}/trace"
echo local > "${TRACE}/trace_clock"
echo "${size}" > "${TRACE}/buffer_size_kb"
echo 1 > "${TRACE}/tracing_on"
