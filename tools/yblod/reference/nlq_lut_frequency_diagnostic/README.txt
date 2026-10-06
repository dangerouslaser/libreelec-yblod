Exact NLQ lookup + read-only frequency diagnostic

SOURCE-ONLY, diagnostic opt-ins; no production default or pixel arithmetic
change beyond the separately validated exact lookup substitution. This package
extends nlq_lut_diagnostic with optional frequency observations and a private
guard supporting explicitly active or inactive Kodi. It is intentionally
separate from that frozen source package.

The lookup contains3x1024 int32 residuals (12,288 bytes), computed through the
native yb_nlq reference for every10-bit enhancement sample. All admitted native
NLQ residuals are bounded[-131072,131071], independently checked before casting.
Polynomial/MMR, sample recovery, residual addition and output quantization remain
unchanged. Requested lookup cannot silently select the integer fallback route.
Metadata caches compare all six fields for all three components, with uploads
before dispatch under existing ownership/pending-work guards. No new fences.

Build/reproduce (Python3.9+, patch):
  python3 stage_diagnostic.py /absolute/reconstruction/repo /fresh/staging
Three canonical edited source files are content-pinned in stage_diagnostic.py;
diagnostic.patch is applied with --fuzz=0 only to private copies. Other engine
sources and SDK dependencies come from the supplied reconstruction/build trees.
Canonical repository sources are never edited by the staging/build tools.
Run the existing LibreELEC SDK compile in a capped offline container:
  docker run --rm --network none --memory 512m --memory-swap 512m --cpus 1 \
    --user 1000:1000 -v MAIN_BUILD:/build:ro -v REPO:/engine-repo:ro \
    -v STAGING:/lab:rw libreelec-dv-build:latest sh /lab/build_nlq_lut_diagnostic.sh
  python3 -m unittest discover -s STAGING -p test_nlq_lut_guard.py
The strict CPU suite checks1,351,680 residuals and13,295,616 final compositions,
including extremes, non-extremal/deadzone samples, cache-field changes and invalid
input atomicity. Separate Python tests check route/oracle/cache count assertions,
frequency shape/device checks and active/inactive Kodi states.
The tested SDK-produced binary SHA256 is:
  c8be1feb9066909e25ed1e91602a0e294e4c7812231d5d77db23254d322b800f
Other compiler/SDK versions may produce another binary and must be repinned.

Private test configuration on the target host:
  python3 prepare_nlq_lut_guard_config.py OUTPUT_JSON LUT_MODE SEQUENCE \
    BINARY SHADER INSTRUCTIONS BL_Y BL_CB BL_CR GUIDE P010 \
    [WARMUPS SAMPLES [FREQUENCY [KODI_STATE]]]
All file paths are absolute regular files. Output is owner-only PRIVATE JSON:
do not publish film/RPU-derived data or hashes. The generator prints the private
configuration digest to supply to the guarded run. The guard pins the explicit
test-host Mesa26.2.4 library set; other drivers need reviewed updates/repinning.
Defaults: warmups8, samples12, frequencyfalse, kodi_stateactive. Repeats are
bounded1..32; A/B/A requires at least2 warmups.32/32 yields65 submitted frames,
64 wrapper-cache hits; enabled LUT has3 builds/uploads and62 cache hits for
A/B/A, or1 build/upload and64 hits for unchanged metadata.

Inside a fresh512MiB/no-swap/CPU1 transient service, create an owned0700 empty
TASK_DIR and run:
  python3 run_nlq_lut_guard.py TASK_DIR PRIVATE_CONFIG EXPECTED_CONFIG_SHA256
The guard never stops, starts, restarts or alters Kodi. In active mode it requires
stable actual kodi.bin PID/start/binary plus active service and an empty
Player.GetActivePlayers RPC response before/after. In inactive mode it requires
exact service Stateinactive, MainPID0 and no actual kodi.bin before/after.
Inactive records explicitly state that RPC was NOT queried: no fabricated idle
playback assertion. External test controller owns any authorized stop/restore.
No claim of continuous service-state monitoring or exclusive GPU use is made.

Environment and timing discipline:
YB_GPU_DIAG_NLQ_LUT=0/1 selects original/exact lookup. YB_GPU_DIAG_FREQUENCY=0/1
is optional, defaults0, and changes observation only. YB_GPU_DIAG_TIMER=0 is
enforced: no accepted zero/unsupported GPU timer values. Reported wall time is
CLOCK_MONOTONIC submit+finish; CPU time is CLOCK_PROCESS_CPUTIME_ID, the whole
process, NOT a thread. Neither is GPU-exclusive kernel time. Resident-input
timings exclude new-frame decode/preparation/upload and full image readback.
The guard rejects several loader overrides but DOES NOT exhaustively reject
inherited Intel/Mesa debug, cache, compiler or instrumentation variables.
Before benchmark claims, independently verify those are absent; in particular
do not mix INTEL_DEBUG/INTEL_SIMD_DEBUG/MESA_GLSL/assembly overrides, shader dump
or cache-control runs with normal timings. Assembly inspection is a separate
untimed diagnostic and requires an explicit reviewed environment record.

Frequency telemetry caveats:
Read-only card0 gt_act_freq_mhz and gt_cur_freq_mhz are sampled before/after
each timed whole-frame submission, OUTSIDE both measured clocks. card0/device
must match renderD128/device. cur is requested frequency; act is actual frequency.
-1 is an unavailable observation, not zero frequency. The guard verifies request,
device association, sample count and integer ranges; it does not require usable
actual frequency readings and MUST NOT be described as proving clock stability.
Endpoint snapshots cannot exclude a transient slowdown during a submission.
Reading sysfs can itself affect between-pass power behavior; compare both routes
with the same observation mode, not against uninstrumented timings as if identical.
No sysfs writes, forced clocks, power-policy changes or driver-queue overrides.
Kernel source for these i915 attributes:
  https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux.git/+/0a85ed6e7fce8075bb3090f8eac05ca1000f5969/drivers/gpu/drm/i915/i915_sysfs.c
Mesa documented debug controls:
  https://docs.mesa3d.org/envvars.html

Accuracy scope:
SEQUENCE1 tests synthetic NLQ-offset A/B/A: three full GPU outputs each checked
against the CPU integer composer with at-most1 native output-code difference;
restored GPU A additionally must match initial GPU A bit-for-bit. B is synthetic
metadata, not a second real RPU. Dump contains initial original-A only.
All submissions check backend completion; only3(seq1)/1(seq0) full-frame CPU
readback oracles are run. Each compares12,441,600 sample values in191 CPU chunks.
The final timed passes use original A. This is not HDMI/SK4/display calibration,
licensed conformance or proof of live playback performance. Source-only build
and CPU checks must not be represented as GPU qualification or a speedup.
