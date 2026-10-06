# Longer playback validation

The observer does not capture film pixels or Dolby instructions. The controller must first
qualify Kodi service shutdown and preserve a recoverable binary/configuration baseline.
Only the controller starts playback, switches routes, builds, or deploys.

Read-only Kodi library confirmation on 2026-10-06:

- 1917: movie ID 51, title `1917`.
- Saving Private Ryan: movie ID 3391, title `Saving Private Ryan`.

Use the same candidate binary and otherwise identical settings for integer/FP32 tests.
Run each movie for 300 seconds from zero, then a matching 300-second window at 1200
seconds. Compare matching windows, not different scenes. Repeat or reverse the order
if differences are small; whole-service lifetime memory peaks inherit earlier runs.
Longer 900-second runs are supported after the 300-second qualification.

Example controller command (create a fresh output directory first):

```
python3 observe_native_movie.py --movie-id 51 --expected-title '1917' \
  --seconds 300 --seek-seconds 0 --expected-route fp32 --label 1917-FP32-300 \
  --expected-binary-sha256 ACTUAL_SHA --output-dir NEW_EXISTING_DIRECTORY \
  --report result.json --stop-on-complete
```

The title is verified against the supplied movie ID before playback. The observer refuses
an existing player, an unexpected binary, a missing display, or an existing report.
Failure markers, wrong composer route, shader generation/compile failure, route fallback,
missing composer observations, and service/binary identity changes invalidate the run.
After failure the controller retains authority over stopping/restarting Kodi; no automatic
service restart occurs. An ordinary Player.Stop is not a service-shutdown qualification.

Report before/after reconstruction helper wall time, other stage times, steady-window
drop/skip deltas, normal-speed/stall flags, deduplicated DRM client engine counters, and
whole-service memory snapshots plus sampled memory availability. The timing summarizer
subtracts cumulative weighted totals rather than averaging cumulative averages. Report
source-time coverage and valid/unavailable DRM intervals. None of these are HDMI flip
counts or exclusive shader GPU time. Pixel accuracy requires separate full-frame tests.

Inspect accepted FP32/integer counts and cache misses throughout each run. Changing
coefficient values can reuse one topology and therefore one cached program. A single
cache miss does not prove metadata was constant, nor prove cache eviction was exercised.
Report naturally observed cache misses; use the standalone A/B/A and topology-transition
tests for controlled cache coverage rather than manufacturing media playback metadata.

Syntax-checked observer and summarizer; summarizer also exercised against the existing
75-second FP32 report and reproduced its 9.228714 ms reconstruction-window result.
Four unit tests cover seek-relative health windows, cumulative timing subtraction,
explicit counter resets, counter regression, and unavailable player/GPU samples.
No longer playback run was performed by this preparation agent.

## Existing baseline versus FP32 result

The original short-run qualification is recorded in
[FP32 playback comparison](FP32_PLAYBACK_COMPARISON.md). These are previously
measured results, not results from the longer tests planned here.

| Measurement | Integer baseline | FP32 candidate |
| --- | --- | --- |
| 1917 reconstruction helper waiting, repeated short runs | 16.42–16.84 ms | 9.23–9.26 ms |
| Steady-window drop/skip counts | 9/12 and 3/4 | 0/0 in both runs |
| Two-frame output comparison | Comparison reference | 99.9148% identical; remaining differences at most one 12-bit code value |

Brightness samples matched exactly. The two-frame comparison is against our integer
implementation, not licensed-device output. One FP32 run had a startup skip outside
the steady window. Reduced reconstruction waiting does not mean an equivalent increase
in overall playback frame rate. Shutdown reliability remains a separate qualification.
