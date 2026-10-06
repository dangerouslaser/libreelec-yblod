# Reduced diagnostic-output transfer experiment

This isolated C runner leaves the shader arithmetic and existing Kodi path unchanged.
It retains all 49,766,400 stage-value comparisons per prepared frame before timing.
During the warmup and three measured passes, it omits CPU output-sentinel uploads
and replaces 48 full diagnostic readbacks with one final-suffix readback
(671,744 bytes for these frames). Every batch still completes a finite upload
wait and dispatch wait. Inputs are still extracted, packed and uploaded each pass.

This intentionally changes the diagnostic workload: timed passes do not perform
full-frame equality checks. A complete untimed GPU/C gate establishes equality,
and every subsequent pass checks all four stages of the final suffix.
It is not a whole-frame-resident pipeline, zero-copy decoding, real-time playback,
SK4 matching or Dolby conformance. Host intervals are not exclusive GPU kernel time.

## VM checkpoint

[Numeric evidence](OUTPUT_TRANSFER_ABBA_RESULTS.json) retains all eight sequential
ABBA cohorts, all phase timings, resource observations and public artifact hashes.
No private input hashes, pixel values or metadata coefficients are published.
Both frames passed complete-stage gates in every cohort. Kodi stayed active;
512 MiB/no-swap guards passed with no memory-limit/OOM events.

| Cohort | Three warm elapsed times (ms) |
|---|---|
| 2296-1-baseline | 456.010, 408.865, 558.346 |
| 2296-2-output | 619.940, 638.606, 526.288 |
| 2296-3-output | 608.135, 641.380, 574.143 |
| 2296-4-baseline | 726.490, 293.175, 565.368 |
| 1406-1-baseline | 445.044, 681.708, 618.882 |
| 1406-2-output | 542.613, 633.088, 630.045 |
| 1406-3-output | 542.094, 584.570, 614.325 |
| 1406-4-baseline | 531.526, 623.225, 570.085 |

Pooled six-pass medians were 507.178 ms baseline versus 614.037 ms reduced-copy
for frame 2296, and 594.483 ms versus 599.447 ms for frame 1406.
There is **no established performance gain**; this experiment is not adopted.
The baseline remains variable, GPU clocks/cache/scheduling are uncontrolled,
and these small cohorts do not establish a general regression either.

Removing these diagnostic copies is not enough on this setup.
The next investigation should isolate repeated input preparation and per-batch
synchronization, without silently moving per-new-frame work outside timing.

## Building and tests

Use the preloaded runner's dependencies, original shader and strict SDK flags,
replacing its main source with
`engine/experimental/native_gpu_scaled_frame_output_probe.c`.
CLI arguments are unchanged. `--validate` and host builds do not execute GPU work.

The inherited synthetic input, width, geometry and suffix-helper guards are
supplemented by structural checks of full-gate readback, bounded warm suffix
readback and finite completion waits. These structural tests do not prove driver
synchronization independently. Sixteen normal and sixteen UBSan tests passed.
