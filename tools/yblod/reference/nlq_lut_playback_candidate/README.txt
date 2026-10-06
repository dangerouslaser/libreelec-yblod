Explicit-options native NLQ lookup playback candidate

Experimental, default OFF. This is the exact residual lookup option integrated
into the standalone C playback engine, not the earlier process-global diagnostic.
No production speedup or live playback qualification is implied by this package.
Default renderer, integer/FP32 controls, pixel rounding, colour stages, scaler,
fences, output ownership and decoder lifetimes are unchanged.

engine.patch adds native_gpu_nlq_lut.c/h and additive create_ex/options APIs.
Old GPU FP32 create always uses original NLQ arithmetic. Old native playback
create retains its existing DVBRIDGE_NATIVE_FP32 environment behavior; new
create_ex takes explicit flags only. There is NO new engine environment variable
or process-global LUT statistics. Version/flags/reserved fields are validated
before allocation; unsupported requested LUT does not silently use integer
fallback. Old create-info and existing statistics layouts remain unchanged.

Native options version1 flags: FP32=1, NLQ_LUT=2; LUT requires FP32.
GPU FP32 options version1 flag: NLQ_LUT=1. Reserved fields must be zero.
Per-wrapper counters own successful shader compiles, exact table builds/uploads,
cache hits and accepted enhancement-enabled LUT submissions. Counters saturate.
Stats getters require caller version1 and exact structure size, same owner thread;
they do not count presented frames. Failed admitted attempts may build/upload a
table without accepting a frame. Backend pointers refer only to wrapper-owned
stats and are destroyed/abandoned before that wrapper is freed.

The table is3x1024 int32 samples,12,288 bytes, computed using exact native yb_nlq.
All admitted residuals fit[-131072,131071], with independent int32/range checks.
Every numeric NLQ field for all three components forms the cache key. Cache-valid
state is published only after successful GL upload. Current native admission is
whole10-bit enhancement-enabled FEL; MEL/disabled enhancement remain unsupported.
Unused disabled NLQ is not precomputed. A bounded shader splice changes only
NLQ residual evaluation, not polynomial/MMR, sample recovery or final quantization.
The existing64KiB backend shader limit remains fail-closed, including generated
topologies exceeding that limit. The pure splice API accepts an exact readable
byte span; no trailing NUL is required, tested against a protected guard page.

kodi-adapter.patch is pinned to installed candidate13/Piers, not pristine Kodi.
Only Kodi reads DVBRIDGE_NATIVE_NLQ_LUT=1, requiring DVBRIDGE_NATIVE_FP32=1.
Unset/0 keeps the old constructor/control path. Native reconstruction must already
be built and requested by its existing controls. Invalid new flag values fail
the native admission attempt. Recreate the context/restart for flag changes.
Existing 'DVBridge native composer:' log appends:
  nlq_lut_enabled accepted_lut nlq_shader_compiles nlq_builds nlq_uploads nlq_cache_hits
These reflect actual context options/routes, not an environment request, using
the existing every120 successfully released frames timing-log cadence.
compatibility.patch adds the helper dependency to existing diagnostic build scripts.

Reproduce in fresh private staging (Python3.9+, patch):
Use a separate engine worktree at pre-integration commit62d30faec9 for this
historical staging package; current branch sources already contain the candidate.
  python3 stage_playback_lut.py REPO FRESH_OUTPUT [CANDIDATE13_KODI_TREE]
Pins cover all patched canonical sources, compatibility scripts and installed
Kodi adapter/header. Stage copies only; supplied repositories are not modified.
Within the existing SDK layout /build=main build, /engine-repo=reconstruction,
/lab=staging, run offline under512MiB/no-extra-swap/CPU1:
  docker run --rm --network none --memory 512m --memory-swap 512m --cpus 1 \
    --user 1000:1000 -v MAIN_BUILD:/build:ro -v REPO:/engine-repo:ro \
    -v STAGING:/lab:rw libreelec-dv-build:latest sh /lab/build_playback_lut_gate.sh
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s STAGING -p test_nlq_lut_guard.py
Optional installed-tree C++ gate in the same capped container:
  python3 /lab/compile_kodi_lut_gate.py
It compiles the actual SDK command with private header overrides, native and
non-native bridge configurations; no full Kodi build, GPU or VA work.

CPU gates cover1,351,680 exact residuals and13,295,616 compositions, non-extremal
and deadzone samples, complete-key mutations, invalid-input atomicity, protected
span boundary, explicit-options preflight and size-safe getters. The real-library
options preflight test uses a no-context callback, not mocked pixel results.
Tested SDK GPU qualifier binary SHA256:
  26577ef93feee773a7280a99ac189e1c3751a9b717cf77b61683f9b40bcc1889
Other compiler/SDK versions require independent binary pins and qualification.

Actual options-route GPU qualification:
The standalone probe shim reads TEST flags and calls the actual create_ex API.
Its statistics come from actual per-context getters, not global diagnostic state.
Fresh private configuration on test host:
  python3 prepare_nlq_lut_guard_config.py OUTPUT_JSON LUT_MODE SEQUENCE \
    BINARY SHADER INSTRUCTIONS BL_Y BL_CB BL_CR GUIDE P010 \
    [WARMUPS SAMPLES [FREQUENCY [KODI_STATE]]]
Paths are absolute regular files; outputs/digests are PRIVATE, never publish
film/RPU-derived data or hashes. Schema:
  yblod.nlq-lut-playback-options-private-guard.v1
In a fresh512MiB/no-swap/CPU1 service with owned0700 empty TASK_DIR:
  python3 run_nlq_lut_guard.py TASK_DIR PRIVATE_CONFIG EXPECTED_CONFIG_SHA256
Defaults8/12 repeats, frequencyfalse, Kodi active. Bounded1..32 repeats; A/B/A
requires at least2 warmups.32/32 produces65 FP32 accepted submits,0 integer,
64 wrapper-cache hits; enabled A/B/A has3 table builds/uploads and62 cache hits,
plus65 actual accepted LUT submits. Disabled LUT reports all LUT counters zero.
Guard requires actual options API/version, pinned inputs/libs/shader/binary,
stable resource/process identities, cleanup and complete CPU/GPU oracles.
Known Intel/Mesa debug/compiler/cache overrides are rejected for these timings;
this is not an exhaustive guarantee against arbitrary external instrumentation.

SEQUENCE1 changes NLQ offsets synthetically A/B/A: three full CPU/GPU comparisons
within1 native output code, plus restored GPU A bit-identical to initial GPU A.
All submits check completion; only3(seq1)/1(seq0) complete readback oracles.
Each oracle checks12,441,600 values in191 CPU chunks; dump contains original A
only. Independent flag0/1 dumps should be byte-compared. No hardware-reference
conformance, HDMI/display accuracy or live-playback guarantee follows from this.

Kodi active mode checks stable service and actual kodi.bin plus empty active-player
RPC before/after. Inactive mode requires exact inactive service, MainPID0 and no
kodi.bin, explicitly NOT querying RPC or fabricating an idle assertion. Guard
does not stop/restore Kodi; external controller owns any authorized operation.
Frequency observation defaults off. When enabled, read-only i915 card0 actual/
requested MHz endpoints are sampled outside measured clocks and device-associated
to renderD128. -1 means unavailable; endpoints cannot exclude transient slowdowns,
prove clock stability or establish exclusive GPU use. Sysfs reads may themselves
affect between-pass power behavior. No forced clocks/policy changes.
Wall is CLOCK_MONOTONIC submit+finish; CPU is CLOCK_PROCESS_CPUTIME_ID (whole
process, not thread). Timings exclude new-frame decode/preparation/upload and full
readback; they are NOT GPU-exclusive kernel time. GPU timers remain disabled.

Historical reproduction:
Earlier nlq_lut_diagnostic, nlq_lut_frequency_diagnostic and gpu_profiling source
pins refer to PRE-integration engine sources (e.g.73e1c1a25d). After applying this
candidate, use a separate engine worktree at that revision for those packages;
do not silently repin them to this engine and call it the same experiment.
