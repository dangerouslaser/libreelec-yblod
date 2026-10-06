# Native NLQ lookup explicit options results

The explicit per-context lookup option passed all eight guarded runs and preserved
the original output exactly. Resident-input host wall timing improved about 24%
on both tested frames, with no timed sample above 10 ms. Earlier matrices still
contain unresolved slow branches; this result supports real-playback opt-in
qualification, not changing the production default.

## Before and after

On 2026-10-06, each frame ran arithmetic/lookup/lookup/arithmetic in ABBA order,
with 32 warmups and 32 timed samples per run. Balanced medians and means pool
64 samples per mode, retaining every sample.

| Frame | Original median ms | Lookup median ms | Median change | Original mean ms | Lookup mean ms | Mean change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1943 | 8.857028 | 6.685974 | -24.5122% | 8.928303 | 6.707857 | -24.8697% |
| 1960 | 8.915996 | 6.748584 | -24.3093% | 8.940205 | 6.761760 | -24.3668% |

| Frame and run | Mode | Wall median ms | Wall range ms |
| --- | --- | ---: | --- |
| 1943 first | Original | 8.857028 | 8.328534 to 9.456411 |
| 1943 second | Lookup | 6.702959 | 6.442808 to 7.107116 |
| 1943 third | Lookup | 6.649052 | 6.357036 to 7.044255 |
| 1943 fourth | Original | 8.898747 | 8.363232 to 9.543261 |
| 1960 first | Original | 8.952180 | 8.384564 to 9.613636 |
| 1960 second | Lookup | 6.795905 | 6.416049 to 7.144377 |
| 1960 third | Lookup | 6.646874 | 6.440854 to 7.051583 |
| 1960 fourth | Original | 8.812856 | 8.312704 to 9.623431 |

All 256 timed samples were below 10 ms. Diagnostic process CPU median increased
from 0.228171 to 0.274245 ms on frame 1943 and from 0.235796 to 0.249023 ms on
frame 1960. The wall-time improvement is not a demonstrated CPU saving. CPU uses
CLOCK_PROCESS_CPUTIME_ID across all diagnostic process threads, not calling-thread
or whole-player CPU.

Timings cover resident-input host submission and completion waits, excluding
new-frame preparation/upload and full-image readback. They are not exclusive GPU
kernel or playback frame times. Saved planes were uploaded, not imported using
VA-API zero-copy. Kodi remained active and idle, not playing video.

## Route and accuracy checks

The probe used the version-one explicit options/statistics API rather than
process-global environment state for selecting each context. All eight runs
accepted 65 FP32 reconstructions, zero integer reconstructions, one shader-cache
miss, and 64 hits, with no shader compilation or generation failures. Lookup
runs accepted 65 lookup frames and performed three table builds/uploads and
62 table-cache hits. Disabled runs performed no lookup work.

Each run exercised synthetic NLQ-offset A/B/A metadata and three complete CPU
oracles, comparing 37,324,800 reconstructed values. Returning to A was bit-exact
over 12,441,600 values. Original outputs matched across modes and matched retained
baseline original-output hashes privately. Against the native integer CPU composer,
luma was exact and all chroma differences were at most one output code in both
modes. This is not Dolby conformance or a real-media RPU-transition test.

The matrix totals 298,598,400 repeated oracle comparisons over two unique saved
frames, not eight independent accuracy frames. All guard checks passed: unchanged
input/executable/driver artifacts, stable idle Kodi identity, device binding,
GL/EGL status, cleanup, and controller exit zero.

Each standalone probe had a one-core quota and 512 MiB memory cap, with no swap.
Peak memory was at most 274.96 MiB and every memory-event counter was zero. One
frame 1960 lookup repeat recorded 2.349 ms of CPU quota throttling over the entire
probe; the other seven recorded zero. These limits and counters do not describe
full Kodi playback memory or isolate timed samples.

## Remaining qualification

The [restored active repeat](NATIVE_NLQ_LUT_ACTIVE_REPEAT_RESULTS.md) retains prior
slow lookup runs and worse mean timing. Their absence here does not prove that
explicit options fixed the underlying timing variability. Real playback must
measure both options on the same installed candidate, with actual route evidence,
whole Kodi CPU, separate GPU-engine counters, drops/skips, and clean shutdown.
The default remains off pending that qualification.

The [scalar results](NATIVE_NLQ_LUT_EXPLICIT_OPTIONS_RESULTS.json) preserve all
wall/process-CPU samples, per-run ranges, accuracy metrics, and resource guards.
