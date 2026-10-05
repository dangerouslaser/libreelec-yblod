# Remaining reconstruction costs

This isolated diagnostic copies the paired MMR benchmark's guards and full
untimed exactness gate, then adds monotonic wall-clock measurements around each
scaled-surface extraction and reconstruction dispatch. It does not change the
composer, the published uninstrumented benchmark or Kodi playback.

The result retains the paired benchmark schema and adds
`instrumented_component_wall_profile: true`, explicit Y/Cb/Cr component order,
and three-repeat extraction/reconstruction arrays for each component/backend.
Preparation remains measured separately. The sum of all measured intervals
must not exceed that repeat's total wall time. Remaining time includes timing
overhead, loop bookkeeping, completion and teardown. Additional clock reads
perturb timing: these totals are not an optimization claim against another run.

## Completed VM diagnostic

[Aggregate evidence](results/native-mmr-component-profile-vm-20261005a.json)
records the 3840x2160 private whole-code frame. Median optimized total was
261.621 ms. Approximate medians for the individual operations were:

| Operation | Time |
| --- | ---: |
| Y extraction | 43.070 ms |
| Cb extraction | 10.783 ms |
| Cr extraction | 11.336 ms |
| Y reconstruction | 35.482 ms |
| Cb reconstruction | 78.533 ms |
| Cr reconstruction | 82.759 ms |
| Preparation | 0.699 ms |

Individual medians need not sum to the median total. Colour reconstruction is
the largest remaining cost, followed by scaled-layer extraction. Reconstruction
timers include validation and four stage writes, not just mapping arithmetic.
The next candidate is reducing repeated per-sample setup in colour mapping,
with any improvement checked against the unchanged equations and reference.

All 49,766,400 stage values across 191 dispatches passed the untimed full-frame
gate. Timed checks cover the last chunk only. The private wrapper verified
inputs, executable, itself and runtime libraries before and after execution.
The pre-exit scope peak was 57,151,488 bytes under a 512 MiB/no-swap limit,
with zero high/max/OOM/OOM-kill events. Kodi stayed active. CPU quota controller
information was unavailable; this snapshot is not lifetime peak or GPU memory.

Hardware scaling, decoding, colour conversion, display and media loading are
outside these intervals. This is neither playback FPS nor independent DV
conformance. No private pixels, metadata coefficients or input hashes are
published.

## Reproduce synthetic guards

Use the build command in NATIVE_MMR_COMPOSER.md, replacing only
`native_scaled_frame_mmr_benchmark.c` with `native_scaled_frame_mmr_profile.c`
and selecting a distinct output executable. All other units remain unchanged.

```sh
python3 -m unittest discover -s tools/yblod/reference -p 'test_native_scaled_frame_mmr_profile.py'
```

The nine tests include inherited malformed-file/alias/metadata guards, full
multi-chunk completion, colour routes and explicit timer accounting. The normal
and undefined-behaviour builds both passed. No movie fixture is needed.
