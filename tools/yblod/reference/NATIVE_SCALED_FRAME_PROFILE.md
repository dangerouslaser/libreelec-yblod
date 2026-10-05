# Instrumented scaled-frame CPU profiling

This separate diagnostic tells us whether time is spent reading the scaled
surface or reconstructing Y, Cb and Cr. It does not change the original
`native_scaled_frame_benchmark.c` or any playback code.

`native_scaled_frame_profile.c` consumes the same six externally pinned,
same-build private inputs as the earlier benchmark: owned instruction blob,
four prepared BL/guide planes and a coherent P010 surface. Inputs must be
distinct regular files with exact byte sizes and stable read identities. BL
values must be whole native10 codes. A full surface preflight rejects any
fractional raw word before profiling. Tokens are caller assertions, not proof
of frame association or hardware synchronization. No fractional policy,
metadata parser, colour conversion or device work is introduced.

One warmup and three measured runs each initialize a fresh integration frame,
visit every Y/Cb/Cr sample sequentially in chunks of at most 65536, and verify
the frame-completion kind, exact component counts and expected chunk counts.
Initialization, surface extraction calls, reconstruction calls and completion
are timed separately. Each component's per-call timings are accumulated across
its complete plane; the report arrays are indexed `[run][Y,Cb,Cr]`. Whole-run
time includes initialization, all loop/instrumentation overhead and completion
validation, but excludes input loading, preflight and context reset.

Both `CLOCK_MONOTONIC` wall time and `CLOCK_PROCESS_CPUTIME_ID` process CPU time
are required. A missing/failing clock rejects the run without a success report;
there is no synthetic zero substitution. Times are checked for valid ordering
and overflow. Only a fully completed cohort emits the final JSON. Completed
earlier calls are not rolled back if a later call fails, but no partial cohort
is reported as complete.

Clock calls perturb execution. Their reading order and surrounding loop/control
costs differ between whole-run and nested per-call intervals. **Stage totals
must not be claimed to sum exactly to either the whole-run time or the separate
uninstrumented benchmark.** These are offline instrumented CPU diagnostics, not
playback FPS, hardware-scaler timing, end-to-end video latency or an accuracy
comparison. All four arithmetic stage arrays are still produced by every
reconstruction call, but this initial profiler does not independently compare
their bytes with a second backend. A later experimental backend requires an
explicit untimed four-stage equivalence gate before paired performance claims.

Host tests inherit the original benchmark rejection cases and add timing-schema
checks plus a complete multi-chunk/partial-tail synthetic frame. The published
checkpoint replay test checks retained aggregate evidence, not a fresh C run.
Build/source/input/library and resource evidence belong to an independently
reviewed execution wrapper; private input hashes and film data must not appear
in a public profiling report.

## Completed LibreELEC CPU checkpoint, 2026-10-05

The [aggregate report](results/native-scaled-frame-profile-libreelec-20261005a.json)
records the reviewed SDK executable's completed CPU-only cohort. Six existing
private benchmark inputs were hash-checked and reused through hardlinks in a
fresh private directory; no media bytes or their hashes are published. The
wrapper verified unchanged binary, inputs, libc/loader and its own bytes before
and after. Source/header inventories also matched before and after execution.
The binary requires only libc dynamically; no FFmpeg, graphics or device library
is linked. GCC 16.2.0 compiled with strict warnings, O2, no fast math, no FP
contraction and no LTO inside a one-CPU/512 MiB/no-job-swap SDK container.

All four complete passes (one warmup, three measured) processed 8294400 Y samples
and 2073600 samples in each chroma component, using 127/32/32 chunks per pass.
Whole-run measured wall times were 651.62/592.17/600.46 ms; process CPU times
646.08/591.27/600.28 ms. Median per-component timings below are computed
independently, not added to claim an exact timing decomposition.

| Component | Surface extraction wall median | Reconstruction wall median |
| --- | ---: | ---: |
| Y | 44.05 ms | 223.99 ms |
| Cb | 11.23 ms | 154.55 ms |
| Cr | 11.37 ms | 156.99 ms |

Reconstruction is the larger measured CPU cost, so reading the scaled surface
is not the leading optimization target in this checkpoint. This is evidence
for prioritization, not proof that a particular replacement is faster or exact.

The VM cohort used a 512 MiB cgroup cap and zero job swap. Its retained in-script
peak snapshot was 56848384 bytes (54.21 MiB), with max/OOM/OOM-kill counters and
swap unchanged at zero. This is not the completed unit's final lifetime peak,
process RSS or GPU memory. CPU quota information was unavailable in the child
scope; this does not establish unrestricted CPU scheduling. Kodi remained
active and settings/display state were not changed. Private evidence remains
retained; there was no new GPU job, capture, decoding or playback accuracy claim.
