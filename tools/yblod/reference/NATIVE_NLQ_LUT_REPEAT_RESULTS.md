# Native NLQ lookup table original metadata repeat

The original-metadata repeat again passed output equivalence checks but did not
establish reliable lookup-table timing. A slow lookup run now occurred on frame
1943 rather than frame 1960. Retain both matrices and keep the option experimental
until this alternating fast and slow behavior is understood.

## Before and after timing

On 2026-10-06, both saved input frames repeated arithmetic/lookup/lookup/arithmetic
in ABBA order with original metadata only. Each run had eight warmups and twelve
samples. Balanced medians pool 24 samples per mode; positive changes mean slower.

| Matrix and frame | Original wall median ms | Lookup wall median ms | Change | Original process CPU median ms | Lookup process CPU median ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Initial synthetic sequence 1943 | 8.945876 | 6.891888 | -22.9602% | 0.294883 | 0.318966 |
| Initial synthetic sequence 1960 | 8.997899 | 11.771331 | +30.8231% | 0.281501 | 0.183140 |
| Original metadata repeat 1943 | 9.001880 | 11.639173 | +29.2971% | 0.169762 | 0.294423 |
| Original metadata repeat 1960 | 9.135101 | 6.729214 | -26.3367% | 0.317362 | 0.323470 |

| Repeat frame and run | Mode | Wall median ms | Wall range ms | Process CPU median ms |
| --- | --- | ---: | --- | ---: |
| 1943 first | Original | 9.009521 | 8.401545 to 9.523415 | 0.174605 |
| 1943 second | Lookup | 6.773615 | 6.515255 to 7.050766 | 0.331517 |
| 1943 third | Lookup | 16.810474 | 16.227580 to 17.261501 | 0.233322 |
| 1943 fourth | Original | 8.892436 | 8.398205 to 9.531433 | 0.160673 |
| 1960 first | Original | 9.022914 | 8.571885 to 9.694271 | 0.330134 |
| 1960 second | Lookup | 6.581311 | 6.430883 to 7.067705 | 0.348992 |
| 1960 third | Lookup | 6.781634 | 6.464991 to 7.137476 | 0.307649 |
| 1960 fourth | Original | 9.135101 | 8.560433 to 9.490947 | 0.304387 |

The slow lookup repeat spans all twelve timed samples. It recorded zero cgroup
quota throttling, as did the slow lookup run in the initial matrix. Its occurrence
without synthetic metadata changes means those changes are not required to
trigger the observed slowdown. This does not identify the cause. Do not discard
either slow run or pool unlike matrices into a single claimed speedup.

CPU timing uses CLOCK_PROCESS_CPUTIME_ID and includes all diagnostic process
threads. It is not calling-thread CPU or whole-player CPU. Wall timing includes
resident-input host submission and completion waits, not exclusive GPU kernel
execution. Saved planes were uploaded for the probe; the measured path excludes
new-frame preparation/upload, full-image readback, VA-API zero-copy import, and
Kodi playback. Kodi remained idle throughout both matrices.

## Accuracy and resource checks

All eight repeat runs completed with cleanup, unchanged executable/input/driver
identities, stable idle Kodi identity, and controller exit status zero. Actual
FP32 reconstruction was accepted with no integer fallback or shader failures.
Original outputs matched exactly between arithmetic and lookup modes, verified
privately. Each repeat run compared 12,441,600 reconstructed values against the
native integer CPU composer: luma exact, chroma differences at most one output
code, unchanged by the lookup option.

Each lookup repeat built and uploaded one exact table and recorded twenty cache
hits. Unlike the initial matrix, these repeats did not change metadata or exercise
restoration to A. The initial three-oracle synthetic A/B/A checks remain qualified
and are reported separately in
[Native NLQ lookup table sequence results](NATIVE_NLQ_LUT_SEQUENCE_RESULTS.md).

The repeat adds 99,532,800 CPU-oracle comparisons to the initial 298,598,400,
totaling 398,131,200 repeated comparisons over **two unique input frames**.
This is not sixteen independent frames or a real-media transition test.

Every repeat probe used a one-core quota, 512 MiB cap, and no swap. Peak memory
was at most 250.67 MiB, and every memory-event counter was zero. One original
frame 1960 run recorded one quota-throttled period totaling 1.026 ms; all other
repeat runs recorded zero. Resource counters cover the entire probe, including
setup and accuracy checks, not just timed samples.

The [longer warmup matrix](NATIVE_NLQ_LUT_LONGER_WARMUP_RESULTS.md) subsequently
showed fast lookup timing on both frames. It retains these slow results and does
not establish their cause or a general playback improvement.

The [repeat scalar results](NATIVE_NLQ_LUT_REPEAT_RESULTS.json) preserve all timing
samples and per-run guards. The [initial scalar results](NATIVE_NLQ_LUT_SEQUENCE_RESULTS.json)
retain the earlier 16.835679 ms lookup median without alteration.
