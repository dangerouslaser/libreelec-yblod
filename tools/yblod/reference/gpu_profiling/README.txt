Standalone GPU profiling diagnostics
===================================

These tools build patched copies in a fresh output directory. They do not
change production backends, public ABI, shader arithmetic, synchronization,
or the canonical 8x8 default. Content hashes pin the four patched source files;
the revision records snapshot context, but content pins are authoritative.
Other dependencies come from the supplied engine checkout and should be pinned
externally when producing comparable measurements. Requires Python 3.9+,
patch, desktop GL/EGL development headers and libplacebo.

Build on Linux:
  python3 build_gpu_profiling.py /path/to/engine-checkout /path/to/private-output
CC, CPPFLAGS and LDFLAGS are supported for the LibreELEC SDK. Use --prepare-only
to review generated patched sources before compiling. Each run creates a new
profiling-source-* directory; nothing is deleted automatically.

Run test-gpu-diag-timer and test-gpu-diag-workgroup: CPU-only mock tests, no GPU.
Default qualified measurement mode: YB_GPU_DIAG_TIMER=0 (unset is equivalent).
Host submit/finish wall and CPU samples are not GPU-exclusive kernel timings.
YB_GPU_DIAG_TIMER=1 is an experimental query diagnostic, NOT qualified for the
tested Mesa 26.2.4 Iris compute path; see the limitation below. Never publish its
samples as GPU performance unless the query's coverage is independently proved.
Use YB_COMPARE_WARMUPS=8 and YB_COMPARE_SAMPLES=12 for both GPU diagnostics.
At most one query per backend and 65 recorded observations per stage are kept.
Queries end before the existing producer fence and are read only after existing
finish; unavailable results fail rather than introducing another wait or poll.

Observed Mesa 26.2.4 Iris timer limitation
----------------------------------------
Both reconstruction and YCC expansion tests returned an available query result
of zero after earlier nonzero results, with no query GL error. Zero is rejected,
not accepted, discarded as an outlier, or converted into a performance number.
Those timer-enabled test runs are invalid measurements. Rejection diagnostics
preserve the queried error, availability, elapsed value, stage and observation
count on stderr, plus numeric backend completion status.

The actual Mesa 26.2.4 source shipped by the build shows:
  src/gallium/drivers/iris/iris_query.c:194-198
    TIME_ELAPSED and TIMESTAMP snapshots are emitted in IRIS_BATCH_RENDER.
  src/gallium/drivers/iris/iris_query.c:435-443
    Only CS-invocation statistics select the compute query batch; timer queries
    select the render query batch.
  src/gallium/drivers/iris/iris_draw.c:394-399
    iris_launch_grid selects IRIS_BATCH_COMPUTE.
  src/gallium/drivers/iris/iris_pipe_control.c:376-418
    memory barriers emit per-batch cache/stall commands for batches with draws.
Upstream source archive: https://mesa.freedesktop.org/archive/mesa-26.2.4.tar.xz
Archive SHA256 from LibreELEC package: bce5f7fbebb934373b86c999a064d52fb5065878dc57f287f95346648ec832e9

These separate batch paths offer a plausible explanation for the untrustworthy
compute timings, not a demonstrated Mesa bug diagnosis. The source does not
prove that every cross-batch dependency is absent. Fresh/delayed query rings or
TIMESTAMP pairs alone are not established fixes; the latter share the same
render snapshot path. No driver queue flags or production fences were changed.
Use timer=0 and report host wall/CPU timing honestly while keeping all output
oracles. Even a nonzero query result is not independently qualified GPU timing.

FP32 reconstruction tool keeps the original standalone probe arguments:
  fp32-timer-compare-probe NODE SHADER width height instructions BL-Y BL-Cb BL-Cr guide P010 [NEW_DUMP]
Its existing integer CPU oracle compares all reconstructed plane codes and
reports native-code differences. That reference is our code, not Dolby hardware.

YCC expansion tool:
  ycc-frame-timer-probe NODE SHADER width height RECONSTRUCTED_DUMP
The input is externally pinned little-endian native-grid Y then Cb then Cr,
12-bit codes in u16 words, no padding (3840x2160 is 24,883,200 bytes).
Only even dimensions up to 3840x2160 are supported. It compares every RGBA32F
component bit-for-bit against an independent integer/dyadic CPU oracle on the
first and final pass. Reads are one row at a time, never a full CPU float image.
Those image checks and input uploads are outside sampled timer windows.
This is chroma expansion, not inherited libplacebo colour processing or HDMI.

Diagnostic YCC workgroups are limited to 8x8, 16x8 and 16x16 with z=1. Actual
linked group dimensions are checked against device axes/invocation limits and
used for both ceil dispatch and group-count bounds. linked_workgroup reports
the successfully linked shader, not a filename-derived guess. Shader variants
must preserve the arithmetic and pass the complete output oracle.

gpu_elapsed_ns is GL_TIME_ELAPSED device command-interval time through the
memory barrier. It is not exclusive kernel cycles: host inter-dispatch gaps,
GPU contention and preemption can influence it. It excludes existing completion
waits, error/image readback and input texture upload. Host submit/finish wall/CPU
arrays remain separate. Timer-enabled measurements should be compared with
timer-enabled measurements; do not silently mix instrumentation modes.

Run under an external 512 MiB memory/no-extra-swap/one-CPU guard and record memory
peak/events. GPU expansion storage itself is roughly 133 MB at 4K. Fail the test
if its existing guard is reached; do not increase limits automatically. Never
run these diagnostics concurrently with playback/capture. Pin binaries, shader,
fixture, driver, node and dependencies externally; reject failed/unclean output.
No film layers, metadata coefficients, capture pixels or private fixture hashes
are distributed with these tools. Public artifacts are source code only.

Guarded YCC invocation
----------------------
run_ycc_timer_guard.sh requires Python 3.11+ (hashlib.file_digest), systemd,
the unified cgroup-v2 hierarchy, and SHA256/core shell tools. This checkpoint
pins the VM's Mesa 26.2.4 library name and loader/dependency paths explicitly;
it intentionally fails on other layouts rather than silently dropping pins.
Kodi must be active with exactly one kodi.bin process and its JSON-RPC endpoint
available without credentials at http://127.0.0.1:8080/jsonrpc. No player may
be active before or after the diagnostic; do not start playback during it.

Prepare a fresh owned empty mode-0700 output directory, then invoke this script
inside an externally created transient service with MemoryMax=512M,
MemorySwapMax=0, and CPUQuota=100% (or lower), passing seven absolute/pinned args:

  sh run_ycc_timer_guard.sh NEW_OUTPUT_DIR BINARY SHADER RECONSTRUCTED_DUMP \
      BINARY_SHA256 SHADER_SHA256 DUMP_SHA256

The guard defaults to YB_GPU_DIAG_TIMER=0. It requires eight warmups and twelve
samples, complete independent two-image bit checks, and successful cleanup.
It records resource events/peak, child exit, artifact/dependency pins and Kodi
process/start/executable identity before and after. Failed runs retain evidence
and are not accepted measurements. Timer-disabled results have no fabricated
gpu_elapsed_ns field. Explicit YB_GPU_DIAG_TIMER=1 is diagnostic only and rejects
zero/missing timer records; even accepted records are not qualified compute
timing on the current driver. Report the timer-disabled host wall/CPU arrays
with their limited scope. No guard invocation automatically creates a cgroup
or alters Kodi/player state.

CPU-only optional-mode tests:
  python3 -m unittest test_ycc_guard_optional_timer.py
