# Longer FP32 playback qualification: completed and interrupted cases

The completed five-minute 1917 comparison again shows substantially less
reconstruction waiting with FP32. The planned eight-case matrix was **not
completed**. Three matrix cases completed observer-integrity, Player.Stop, and service-shutdown checks;
the resumed integer control was deliberately interrupted after visible drops
were reported, and the controller restored the faster route.
A separate later FP32-only SPR 20-minute-window run also completed those checks.

The integer start-window control showed 16 drops and 36 skips: its timing and
lifecycle checks completed, but it did **not** qualify smooth playback.

These compare the current native integer control with the current FP32 route,
using one candidate binary. They are not an untouched CroqueMr benchmark.

## Matched five-minute 1917 start window

| Measurement | Integer | FP32 |
| --- | ---: | ---: |
| Reconstruction helper waiting | 16.451553 ms | 8.993345 ms |
| Steady-window drops / skips | 16 / 36 | 0 / 0 |
| Deduplicated Kodi DRM Render busy | 65.4026% | 61.8264% |
| DRM Video busy | 6.4894% | 6.5247% |
| DRM Video-enhance busy | 7.6564% | 9.4496% |
| Whole-service lifetime peak memory | 1.962 GB | 1.941 GB |
| Observer integrity, player stop, and service shutdown | Passed | Passed |

Reconstruction waiting fell **45.3344%**. This is not a 45% overall playback
frame-rate improvement. Helper waiting includes CPU-side completion waits;
DRM counters are not isolated kernel timings or frequency-normalized power
measurements. Released operation counts are not unique displayed frames.

The steady health windows cover approximately 10–290 seconds in both runs.
FP32 had one skip before that window and none within it. Both runs used fresh
service starts, but memory peaks still include the whole service rather than
just the engine; the small memory difference is not evidence of an allocation
optimization.

## Other completed observations

| Observation | Reconstruction waiting | Steady drops / skips | Qualification |
| --- | ---: | ---: | --- |
| 1917 FP32, five minutes from the 20-minute point | 8.779186 ms | 0 / 1 | Playback, stop, shutdown passed; no completed matching integer control |
| Saving Private Ryan FP32, separate five-minute start window | 9.313362 ms | 0 / 0 | Separate FP32-only observation; no matched control or stop/shutdown qualification |
| Saving Private Ryan FP32, separate five minutes from the 20-minute point | 9.620517 ms | 0 / 0 | Observer, stop, and clean service shutdown completed; no matched integer control |

The Saving Private Ryan observations used existing service lifetimes and their
memory peaks inherit earlier work. Neither is an additional completed matrix
case. The 20-minute window had one startup skip but none in its steady health
window, and its clean shutdown was checked independently in the bounded journal.
These observations do not establish comparative performance on that film.

## Interrupted control and execution history

The resumed 1917 integer control at the 20-minute point reached 13 total drops
and 24 total skips in its saved partial log before interruption. Its partial
weighted reconstruction wait was 16.665125 ms. It did not complete its intended
300-second window or its own stop/shutdown qualification. Comparing that number
with a completed five-minute FP32 result is not a matched-duration benchmark.

The first controller had already completed the first two observer/lifecycle cases, then stopped
because the observer used an invalid Kodi seek parameter shape. The seek tool
was corrected and the next case explicitly resumed in a fresh directory.
That resumed FP32 case completed those checks; its following integer control was interrupted
for the visible-drop concern. This is three completed observer/lifecycle cases across two
executions, not one continuous successful eight-case matrix or a pipeline crash.

The running controller's journal filter began after RPC readiness. Entire
bounded Kodi journals were therefore checked independently from before startup:
two starts for the original pair and two for the resumed FP32/interrupted
integer cases, with no crash or failure markers. Completed-case logs showed
no release fallback, retained native cleanup/quarantine, or child crash markers.
The published controller source now records the journal boundary before startup;
that source improvement must not be retroactively attributed to these runs.

## Accuracy and remaining qualification

The user also watched the numbered FEL test clip after Saving Private Ryan and
reported that it finished and “looked perfect.” Logs identified FP32 and FEL;
the available partial logs through approximately 110 seconds showed zero drops
and two skips including startup. There was no formal full-clip observer report.
This is useful user-reported visual evidence, not quantified display accuracy or
a complete-clip counter qualification.

These playback observers do not capture pixels. Arithmetic accuracy is covered
separately by the [four-frame check](EXPANDED_FP32_ACCURACY.md), and the measured
difference from saved hardware output by the [paired SK4 check](PAIRED_FP32_SK4_FRAME1943_RESULTS.md).
A one-code reconstructed-plane bound is not a one-code final transport bound.

The complete SPR paired windows and the complete matching 1917 20-minute integer
control remain unqualified. Avoid additional slow-control TV playback unless
the controller explicitly chooses it. Further FP32-only sustained playback,
display-mode changes, and broader stop/restart coverage can be checked without
presenting this interrupted matrix as complete. The final-display-restoration
ownership safeguard is not proof that the underlying restoration failure has
been eliminated.

After the clean SPR 20-minute-window shutdown, a **separate menu-only short-start
shutdown timed out and was force-killed with SIGKILL**. Its bounded journal did
not show an explicit heap abort, but it was not a clean exit. Shutdown is therefore
not generally resolved; do not treat the successful playback stops as proof that
all restart scenarios are fixed.

[Scalar evidence](PARTIAL_LONG_FP32_PLAYBACK_RESULTS.json) contains completed,
unmatched, and interrupted results separately. Private film paths, source
hashes, pixels, Dolby instructions, raw logs, and process identities are excluded.
The public `observe_native_movie.py`, `summarize_long_playback.py`, and
`run_long_matrix.py` provide bounded collection and explicit resume behavior.
