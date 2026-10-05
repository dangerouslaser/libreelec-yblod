# Exact enhancement-correction table experiment

`engine/experimental/native_gpu_scaled_frame_nlq_lut_probe.c` is an isolated
companion to the preloaded-batch probe. It replaces repeated enhancement
correction arithmetic with a small table derived from the current frame's
metadata. Mapping, composition, rounding and clipping policies are unchanged.
The existing probes, reference shader and Kodi playback path are unchanged.

For this explicit 10-bit EL experiment, each component has 1,024 possible
integer input codes. The unchanged C `yb_nlq` computes every signed correction
once: 3,072 signed 32-bit entries, or 12 KiB. GPU binding 3 reads the table by
component and native code; the input is not silently rounded or rescaled.
This is mathematical caching, not a fitted colour adjustment or SK4 matching.

The helper validates all three configurations and their common denominator
before replacing the caller's table. Invalid configurations leave that output
unchanged. Eight-bit EL metadata is outside this table experiment and is
explicitly rejected rather than reinterpreted as ten bits; the wider native
reference contract is unchanged. New metadata requires a freshly built table,
so a previous frame's corrections cannot silently be reused.

## Timing scope

`lut_generation_wall_ns` and `lut_generation_cpu_ns` record the one-time
metadata-dependent table preparation separately from warm frame timing.
The hardware path uploads the table before other sample-buffer allocations and
waits for a finite completion fence; `lut_upload_wall_ns` records that interval
inside cold setup. Host-only validation reports zero upload time.
Its initialization and upload
cost must remain visible in the checkpoint; warm dispatch timings alone are
not the end-to-end cost of changing metadata every frame.

The preloaded diagnostic still transfers, waits for and reads each batch;
it is not a whole-frame-resident production pipeline. Host dispatch/wait
intervals are not device elapsed time or exclusive shader busy time. Compare
only clearly labelled workloads and preserve the complete untimed correctness
gate before interpreting speed observations.

## Measured ABBA checkpoint

Eight fresh-process cohorts ran in this exact order: baseline, table, table,
baseline for prepared frame 2296, then the same order for frame 1406. Each
cohort used one warmup and three measured complete-frame passes. Frame 2296
used its Intel-scaled P010 input; frame 1406 used its software-linear P010
input. Their distinct pictures and metadata do **not** establish a comparison
of hardware versus software scaling.

Every cohort passed all 49,766,400 full-frame stage comparisons before timing:
48 GPU batches and 191 bounded CPU oracle dispatches. All memory-limit/OOM
events and job swap were zero under the 512 MiB ceiling. The largest charged
peak was 144,994,304 bytes; this is not a bound on all system/GPU allocations.
Kodi stayed active and inputs, wrappers and runtime identities were unchanged.

All three warm timing observations are shown below, in milliseconds. The
[complete public evidence](NLQ_LUT_ABBA_RESULTS.json) also preserves every
dispatch/wait, preload-wait, CPU, cold-setup, teardown and table-setup timing,
along with resource snapshots and exact source/shader/executable pins.

| Order | Prepared frame | Path | Warm elapsed ms (1, 2, 3) | Process CPU ms (1, 2, 3) |
|---|---:|---|---|---|
| 1 | 2296 | baseline | 621.149834, 646.368310, 763.346555 | 188.914239, 193.851901, 259.524293 |
| 2 | 2296 | lut | 639.839959, 541.543220, 545.445156 | 232.267677, 294.486323, 264.120981 |
| 3 | 2296 | lut | 593.224995, 536.412064, 493.487301 | 218.880778, 292.079230, 247.069532 |
| 4 | 2296 | baseline | 406.820397, 297.127703, 298.430083 | 170.842516, 161.673825, 160.187193 |
| 5 | 1406 | baseline | 289.365572, 472.720909, 546.563114 | 164.711526, 194.908596, 222.092526 |
| 6 | 1406 | lut | 497.038558, 325.403886, 291.053223 | 204.806836, 173.443867, 170.717397 |
| 7 | 1406 | lut | 608.823911, 420.810697, 613.625676 | 198.516252, 187.941885, 208.324099 |
| 8 | 1406 | baseline | 424.019691, 578.696763, 612.794680 | 168.196638, 220.094150, 234.753493 |

Across the six warm observations per path and frame, median elapsed times
were:

| Prepared frame | Baseline median ms | Table median ms |
|---|---:|---:|
| 2296 | 513.9851155 | 543.494188 |
| 1406 | 509.6420115 | 458.9246275 |

**No performance gain is established and this experiment is not adopted.**
The direction differs between frames and the baseline itself changes markedly
between surrounding cohorts. ABBA ordering exposes that variability; it does
not make these small runs a continuous-movie or sustained-performance test.

Table generation took 31,015–34,708 ns per supplied frame. Completion-fenced
table upload took 418,101–558,337 ns and is already included in cold setup,
not in the warm totals above. Both costs must remain visible when considering
new metadata every frame. The first table cohort's 118,023,990 ns cold setup
is published too; driver shader-cache state was uncontrolled.

Exactness here means agreement with our unchanged C reference, not Dolby
conformance, matching a licensed player, or validated Kodi playback. Warm
passes retain final-suffix checks; the complete GPU/reference gate occurs
before timing rather than during every measured pass.

The saved-evidence audit checks public provenance, geometry, complete-stage
counts, all timing fields, memory/swap guards and privacy constraints without
opening a GPU:

```sh
cd tools/yblod/reference
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_native_gpu_nlq_lut_abba_results
```

## Host-only gates

The synthetic helper harness compares all 3,072 table entries with the unchanged
reference for multiple configurations, including minimum/maximum denominators,
endpoint offsets, coefficient limits, zero correction, negative flooring,
limiting before flooring and metadata reconfiguration. It tests late invalid
configurations and null arguments without overwriting output sentinels.
Inherited tests cover complete-frame input validation, batch/subchunk tails,
actual suffix-helper bounds, width rejection and preload timing order.

Host and UBSan runs execute no GPU work and cannot establish device speed or
shader/table agreement. A hardware checkpoint must compare every value across
all four reconstruction stages against the unchanged C engine, pin the new
main C file and table shader, and record all resources and timing scopes.

Build using the preloaded probe's dependencies and strict flags, replacing only
its main C file with `native_gpu_scaled_frame_nlq_lut_probe.c`. CLI arguments
are unchanged; `--validate` and `YB_GPU_PROBE_HOST_ONLY` remain CPU-only.
Fractional Y416 transport, surface sharing, real-time playback and Dolby display
conformance remain outside this experiment.
