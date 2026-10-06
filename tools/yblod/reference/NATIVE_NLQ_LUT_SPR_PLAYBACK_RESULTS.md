# Native NLQ lookup Saving Private Ryan playback results

The opt-in lookup reduced composer helper waiting by **28.03%** and render-engine
busy time by **6.41 percentage points** during this Saving Private Ryan scene.
Both candidate runs repeated the gain. All four three-minute cases had zero
steady playback drops/skips, no stalls, and clean shutdowns. The first control
had one startup skip; all other observed cumulative drop/skip totals were zero.

## Before and after playback

On 2026-10-06 the same installed candidate played from 20 minutes for 180 seconds
per case in lookup off/on/on/off order. Kodi restarted and settled for at least
20 seconds each time. Both conditions used FP32 and metadata-only colour handoff;
only the explicit per-context lookup option changed.

| Run | Lookup | Composer helper wait ms | Whole Kodi CPU percent of one core | Render client busy percent | Raw cumulative drops and skips | Clean shutdown |
| --- | --- | ---: | ---: | ---: | --- | --- |
| First control | Off | 9.523765 | 19.6535 | 65.4758 | 0 and 1 | Yes |
| First candidate | On | 6.846382 | 19.9372 | 58.9580 | 0 and 0 | Yes |
| Repeat candidate | On | 6.871882 | 19.5094 | 58.8916 | 0 and 0 | Yes |
| Final control | Off | 9.538559 | 19.6244 | 65.1873 | 0 and 0 | Yes |

| Balanced metric | Lookup off | Lookup on | Change |
| --- | ---: | ---: | ---: |
| Composer helper wait ms per release | 9.531162 | 6.859132 | -28.0347% |
| Whole Kodi CPU percent of one core | 19.6389 | 19.7233 | +0.4298% |
| Render client busy percent | 65.3315 | 58.9248 | -6.4067 percentage points |
| Video client busy percent | 5.3227 | 5.3330 | +0.0103 percentage points |
| Video enhancement client busy percent | 9.4175 | 9.4844 | +0.0668 percentage points |
| YCC helper wait ms per release | 5.326794 | 5.345132 | +0.3443% |

Helper comparisons pool weighted cumulative timing differences over 8,160 releases
per route. GPU counters are deduplicated Kodi DRM client counters weighted by
elapsed time; copy-engine busy was zero. CPU includes all Kodi user/kernel threads
and is normalized so 100% occupies one core. Overall CPU was essentially unchanged,
so this is composer/render headroom rather than a demonstrated CPU improvement.

## Qualification and timing limits

Both candidate composer values were below both controls. Only two repeats per
condition and one scene were tested; cumulative rounding contributes about
0.00053 ms per case, not a confidence interval for system variance. Helper waits
are host completion waits, not exclusive GPU execution or total player frame time.
Available cumulative averages cannot supply per-frame percentiles or long-tail
counts. Do not sum overlapping waits or translate this directly into FPS.

Each steady health window spans about 160.16 seconds with normal speed and no
stalls, drops, or additional skips. Raw startup-inclusive counters remain shown
above. Actual composer logs verified FP32, zero integer fallback, no shader or
generation failures, and the requested lookup route. Each enabled case accepted
4,200 lookup operations, compiled one lookup shader, built/uploaded one table,
and recorded 4,199 table hits. Disabled cases reported no lookup work. Live table
metadata remained stable in this scene; rebuild transitions were not exercised.

Player-stop idle checks, candidate binary/service identity, entire startup-to-stop
journals, and clean service exit passed for all four cases. The controller exited
zero and restored the prior override. Any subsequent operator-selected configuration
or Kodi startup is separate from this completed matrix; production default remains off.

Whole-service memory peaks in test order were 2011.14, 1752.17, 1891.38, and
1885.13 MiB. These are full Kodi lifetime peaks, not engine-only memory or the
standalone 512 MiB limit. Variation does not establish a memory saving; the
playback observer does not qualify memory-event/OOM counters.

## Accuracy and remaining coverage

Playback counters do not measure pixels. The separate
[explicit options GPU checks](NATIVE_NLQ_LUT_EXPLICIT_OPTIONS_RESULTS.md) preserved
output across modes and against retained original baselines on two saved frames,
including synthetic metadata A/B/A and exact restoration. Luma matched the native
integer CPU composer exactly; chroma differences stayed within one output code
in both modes. That is unchanged tested numerical behavior, not Dolby conformance,
licensed hardware matching, or accuracy improvement from the lookup.

The [1917 matrix](NATIVE_NLQ_LUT_1917_PLAYBACK_RESULTS.md) separately reduced composer
waiting 22.19% and render busy 4.79 percentage points with zero observed drops/skips.
Together the films provide eight clean playback/stop/shutdown cases and gains
that repeat in two scenes. Broader metadata changes, seeks, longer playback,
and lifecycle coverage are still needed before default adoption.

The [earlier active standalone repeat](NATIVE_NLQ_LUT_ACTIVE_REPEAT_RESULTS.md)
retains slow lookup branches and worse means. These mixed standalone results
remain relevant; live cumulative averages cannot prove the branches disappeared.
Exact scalar windows and route/lifecycle guards are in the
[machine-readable results](NATIVE_NLQ_LUT_SPR_PLAYBACK_RESULTS.json).
