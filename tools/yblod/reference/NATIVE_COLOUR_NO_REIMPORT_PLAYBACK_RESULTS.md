# Native colour metadata handoff playback results

Skipping redundant base-layer and enhancement-layer imports reduced colour
handoff setup time by **30.09%**, or **0.08267 ms per call**, in this 1917 test.
Both routes used the same FP32 reconstruction engine and installed binary.
All four playback runs had zero observed drops or skips and clean player and
service shutdowns. This is a small CPU-side cleanup, not a demonstrated GPU
throughput improvement. The patch remains opt-in.

## Before and after

The 2026-10-06 matrix played the same Profile 7 FEL scene from 20 minutes for
180 seconds per run. A is the original base-layer and enhancement-layer reimport
path; B uses only the colour metadata after reconstruction. The order was ABBA,
with a fresh Kodi service and at least 20 seconds of startup settling each time.

| Run | Imports | Handoff wall ms | Handoff thread CPU ms | Whole Kodi CPU percent of one core | Composer wait ms | Drops and skips | Clean shutdown |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| A first | Original | 0.272500 | 0.272059 | 20.605 | 8.897147 | 0 and 0 | Yes |
| B first | Metadata only | 0.192657 | 0.191657 | 20.645 | 8.956543 | 0 and 0 | Yes |
| B repeat | Metadata only | 0.191382 | 0.190382 | 20.582 | 9.091794 | 0 and 0 | Yes |
| A repeat | Original | 0.276829 | 0.275829 | 21.359 | 8.853086 | 0 and 0 | Yes |

| Balanced comparison | Original | Metadata only | Change |
| --- | ---: | ---: | ---: |
| Handoff wall ms per call | 0.274696 | 0.192029 | -30.0939% |
| Handoff thread CPU ms per call | 0.273971 | 0.191029 | -30.2740% |
| Whole Kodi CPU percent of one core | 20.9825 | 20.6136 | -1.7582% |
| Composer wait ms per release | 8.874797 | 9.023188 | +1.6721% |
| GPU render client busy percent | 61.6840 | 62.0656 | +0.3816 percentage points |
| GPU video client busy percent | 6.6322 | 6.6361 | +0.0039 percentage points |
| GPU video enhancement client busy percent | 9.4401 | 9.4433 | +0.0032 percentage points |

Handoff and composer comparisons pool cumulative timing differences by call
count, with 8,280 measured calls per route. CPU comparisons pool process CPU
seconds over observed wall seconds. GPU comparisons are time-weighted,
deduplicated DRM client busy counters. Copy-engine busy counters were zero.

## Variation and timing scope

The targeted handoff improvement repeated in both B runs. The original handoff
wall time varied from 0.272500 to 0.276829 ms; metadata-only varied from 0.192657
to 0.191382 ms. Rounding of cumulative log averages contributes at most about
0.00053 ms uncertainty per run. These bounds cover log rounding, not run-to-run
variance or a statistical confidence interval.

Whole Kodi CPU changed more between the original endpoints than the pooled
before-and-after difference. The small apparent overall CPU reduction is not
a reliable whole-player performance win. Composer waiting was slightly higher
with metadata-only, and GPU busy counters were essentially similar. Do not add
these stage waits to predict frame time: they can overlap and include host waits.

The handoff timer covers wrapping, colour preparation, flushing, and destroying
the temporary wrapper; it excludes native reconstruction release. Thread CPU
measures the calling thread. Whole-process CPU includes every Kodi thread,
normalized so 100% means one fully occupied CPU core. Neither is exclusive GPU
execution time, unique displayed-frame rate, or HDMI presentation timing.

## Playback and lifecycle checks

Every observed health line reported normal speed, no stalls, zero cumulative
drops, and zero cumulative skips. The comparable steady windows span about
160.16 seconds after startup. Presented-frame logs verified the actual import
route; composer logs verified FP32 work, zero integer fallback, and no shader
compilation or generation failures. Observer identity, binary identity, and
player-stop checks passed. Full startup-to-stop journals showed clean service
deactivation, with exit status zero and no forced termination. The controller
completed all four cases with exit status zero and restored its original override.
The test operator subsequently selected the opt-in flag on the test device;
the production default was not changed by this test.

| Run | GPU render percent | GPU video percent | GPU video enhancement percent | Service lifetime peak MiB |
| --- | ---: | ---: | ---: | ---: |
| A first | 61.6769 | 6.6363 | 9.4397 | 1814.36 |
| B first | 61.9567 | 6.6305 | 9.4385 | 1695.18 |
| B repeat | 62.1744 | 6.6416 | 9.4481 | 1751.88 |
| A repeat | 61.6912 | 6.6280 | 9.4405 | 1763.20 |

Memory is for the whole Kodi service, not just this engine. Playback used no
configured 512 MiB service limit; the earlier standalone probe limit does not
apply. The host had no installed swap. These observations do not constitute
memory-event or OOM counter qualification because this observer does not collect
those counters. Peak memory variation does not establish an allocation saving.

## Accuracy and remaining scope

Playback counters do not measure pixel accuracy. The separate full-resolution
entry-path test passed 33,177,600 float-bit comparisons, all 128 metadata packet
words, and two invalid-input cases for this candidate. That validates the tested
entry-path equivalence, not Dolby conformance or display-output matching.

This playback matrix covers one scene with two repetitions per route. Broader
film, seek, metadata-transition, and lifecycle testing remains necessary before
enabling the option by default. Clean shutdown here does not resolve the separate
short-start shutdown timeout documented in
[Native Kodi shutdown diagnosis](NATIVE_KODI_SHUTDOWN_DIAGNOSIS.md).
Exact scalar windows, engine counters, and memory observations are in the
[machine-readable results](NATIVE_COLOUR_NO_REIMPORT_PLAYBACK_RESULTS.json).
