Exact NLQ lookup-table diagnostic (not a production default)

This replaces only FP32 composer's per-pixel integer NLQ residual arithmetic
with an exact CPU-precomputed 3x1024 int32 lookup (12,288 bytes). Polynomial/MMR,
sample reconstruction, residual addition and output quantization are unchanged.
The admitted native NLQ residual range is [-131072,131071]; every table entry
is computed through yb_nlq and independently checked before int32 conversion.
Invalid configurations fail closed. Existing integer-only LUT experiment supplied
the idea; this package additionally exercises the actual playback FP32 wrapper.

Enable YB_GPU_DIAG_NLQ_LUT=1; 0/unset preserves original arithmetic. Requested
lookup routes cannot silently fall back to integer. Cached configurations compare
all six NLQ fields for all three components. Uploads occur before dispatch under
existing pending-work guards, without changing completion fences or ownership.

Stage copies (Python3.9+, patch):
  python3 stage_diagnostic.py /absolute/reconstruction/repo /fresh/staging
The three edited canonical sources are content-pinned inside the staging tool.
The build script targets the existing LibreELEC SDK, with /build main build tree,
/engine-repo reconstruction repo, and /lab staged diagnostic. Run it inside:
  docker run --rm --network none --memory 512m --memory-swap 512m --cpus 1 \
    --user 1000:1000 -v MAIN_BUILD:/build:ro -v REPO:/engine-repo:ro \
    -v STAGING:/lab:rw libreelec-dv-build:latest sh /lab/build_nlq_lut_diagnostic.sh
No full Kodi build is needed. CPU tests include 1,351,680 exact residual and
13,295,616 composition comparisons, extremes, non-extremal samples, cache-field
invalidation, malformed input atomicity and shader-splice rejection.
  python3 -m unittest discover -s STAGING -p test_nlq_lut_guard.py

Private test host configuration:
  python3 prepare_nlq_lut_guard_config.py OUTPUT_JSON LUT_MODE SEQUENCE \
    BINARY SHADER INSTRUCTIONS BL_Y BL_CB BL_CR GUIDE P010
Paths are absolute, regular files. Its JSON/output digest is PRIVATE: never
publish film-derived data or hashes. It pins the test host's explicit Mesa26.2.4
library set; other versions require a reviewed guard update and repinning.
Optional WARMUPS SAMPLES arguments after P010, or integer config fields warmups
and samples, select bounded1..32 repeats; defaults8/12. A/B/A needs at least2
warmups.32/32 yields65 accepted submissions,64 wrapper-cache hits and, with
lookup enabled,62 LUT-cache hits for A/B/A or64 for ordinary single-metadata.
CPU samples use CLOCK_PROCESS_CPUTIME_ID (whole process, not a thread clock).

Inside a fresh memory512MiB/no-swap/CPU1 transient service, create an owned0700
empty TASK_DIR and run:
  python3 run_nlq_lut_guard.py TASK_DIR PRIVATE_CONFIG EXPECTED_CONFIG_SHA256
The guard requires Kodi idle before/after, unchanged actual kodi.bin process and
binary, exact libraries/inputs/shader, zero cgroup events/swap, requested actual
FP32/LUT routes, full-plane CPU oracles, cleanup success and positive host timings.
Do not run concurrently with playback or another GPU test.

SEQUENCE=1 validates synthetic NLQ-offset A/B/A: three complete GPU outputs each
compared with the CPU integer composer (one-code FP32 tolerance); restored A is
also compared bit-for-bit against the initial GPU A. The dump contains initial
original-A only. B is synthetic metadata, not a second media/RPU reference.
All21 submissions must select FP32; only the first three have complete readback
oracles. Eight warmups and twelve timed submissions then use original A.
Expected LUT counters: one shader, three builds/uploads, eighteen cache hits.
SEQUENCE=0 uses one full oracle, one build/upload, twenty cache hits.
Both modes compare 12,441,600 native sample values per full-frame oracle in191
CPU chunks. Final scalar reports must distinguish composer code deltas from
SK4/HDMI/display comparisons: this test does not measure those.

YB_GPU_DIAG_TIMER=0 is enforced: wall/CPU measurements are submit+completion
host timings, NOT GPU-exclusive kernel time. Existing Mesa Iris compute-queue
timer-query zeros are rejected rather than represented as valid performance.
No performance or GPU accuracy result is claimed by this source-only package.
