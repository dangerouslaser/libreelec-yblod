# Native NLQ lookup 1917 playback results

The opt-in NLQ lookup reduced composer helper waiting by **22.19%** during real
1917 playback and lowered Kodi render-engine busy time by **4.79 percentage
points**. All four three-minute runs had zero observed drops or skips and clean
shutdowns. This is a qualified improvement for one scene, not a production-default
decision or an accuracy improvement.

## Before and after playback

On 2026-10-06 the same installed candidate played 1917 from 20 minutes for 180
seconds per case in lookup off/on/on/off ABBA order. Each case restarted Kodi
and settled for at least 20 seconds. Both conditions used FP32 reconstruction
and metadata-only colour handoff; only the explicit lookup option changed.

| Run | Lookup | Composer helper wait ms | Whole Kodi CPU percent of one core | Render client busy percent | Drops and skips | Clean shutdown |
| --- | --- | ---: | ---: | ---: | --- | --- |
| First control | Off | 8.880971 | 20.7903 | 61.8732 | 0 and 0 | Yes |
| First candidate | On | 6.898600 | 20.2046 | 56.9222 | 0 and 0 | Yes |
| Repeat candidate | On | 6.719000 | 20.2613 | 56.5976 | 0 and 0 | Yes |
| Final control | Off | 8.620441 | 20.5739 | 61.2247 | 0 and 0 | Yes |

| Balanced metric | Lookup off | Lookup on | Change |
| --- | ---: | ---: | ---: |
| Composer helper wait ms per release | 8.750706 | 6.808800 | -22.1914% |
| Whole Kodi CPU percent of one core | 20.6821 | 20.2331 | -2.1708% |
| Render client busy percent | 61.5489 | 56.7590 | -4.7898 percentage points |
| Video client busy percent | 6.6459 | 6.6523 | +0.0064 percentage points |
| Video enhancement client busy percent | 9.4299 | 9.4539 | +0.0240 percentage points |
| YCC helper wait ms per release | 5.100206 | 5.100957 | +0.0147% |

Composer averages are weighted differences of cumulative timing totals over
8,160 control and 8,400 candidate releases. GPU counters are deduplicated Kodi
DRM client counters weighted by elapsed time; copy-engine busy was zero. CPU
uses all Kodi user/kernel process ticks, normalized so 100% occupies one core.
The small overall CPU difference is secondary to the more substantial repeated
composer/render reduction.

## Timing scope and variation

Control composer waiting changed from 8.880971 to 8.620441 ms, while candidate
waiting changed from 6.898600 to 6.719000 ms. Both candidate runs were lower than
both controls, but only two repetitions per condition were tested. Cumulative
log rounding contributes about 0.00053 ms per run; it does not bound system
variance or provide a statistical confidence interval.

Helper waiting includes host completion waits and is not exclusive GPU execution
time or total player frame time. The available cumulative averages cannot supply
per-frame p95/p99 or count long timing tails. GPU-engine busy counters are not
isolated shader timings or proof of exclusive GPU ownership. Do not sum these
overlapping stage waits or convert their reduction directly into playback FPS.

The [earlier restored-active standalone test](NATIVE_NLQ_LUT_ACTIVE_REPEAT_RESULTS.md)
had worse lookup means and long waits despite better medians. Those results remain
valid for that workload. Their absence from playback health here does not prove
that the underlying timing branches disappeared, because playback logs do not
contain individual-frame timing samples.

## Route and lifecycle qualification

Presented logs verified metadata-only handoff for both conditions. Composer logs
verified FP32 acceptance, zero integer fallback, and no shader compilation or
generation failures. Enabled runs each accepted 4,320 lookup operations, built
and uploaded one table, compiled one lookup shader, and recorded 4,319 table hits.
Disabled runs reported no lookup work. This scene exercised stable table metadata,
not a table-rebuild transition in live playback.

All observed health counters stayed at zero drops and zero skips, with normal
speed and no stalls. Comparable steady windows span about 160.16 seconds per case.
Player stop, binary/service identity, full startup-to-shutdown journals, and clean
service exit checks passed. The controller completed with exit zero and restored
the previous override without automatically restarting playback.

Whole Kodi service lifetime peaks were 1780.90, 1784.19, 1753.96, and 1826.59 MiB
in test order. Playback did not use the standalone 512 MiB probe cap. These peaks
are not engine-only memory and do not establish a memory saving. The observer
does not qualify memory-event or OOM counters.

## Accuracy and build evidence

Playback counters do not measure pixels. The separate
[explicit options GPU matrix](NATIVE_NLQ_LUT_EXPLICIT_OPTIONS_RESULTS.md) passed
three synthetic metadata CPU oracles per run, original-output equivalence across
both modes and against retained baseline outputs, and restoration-to-A checks.
It tested two unique saved frames repeatedly: exact luma and chroma differences
at most one output code against the native integer CPU composer in both modes.
That is unchanged numerical behavior, not licensed Dolby conformance or display
matching. Real playback metadata transitions and broader scenes remain to test.

The full candidate build completed under a 4 GiB, one-core, no-swap build limit,
with serial compile/link scheduling. Peak build memory was 2,334,003,200 bytes,
with zero recorded memory events and swap. Build resource checks are separate
from live-player memory observations.

The option remains off by default. A second film and broader real metadata/lifecycle
coverage are needed before adoption. Exact scalar windows and per-case guards
are retained in the [machine-readable results](NATIVE_NLQ_LUT_1917_PLAYBACK_RESULTS.json).
