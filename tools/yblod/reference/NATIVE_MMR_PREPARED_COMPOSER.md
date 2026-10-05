# Prepared colour code decisions

This candidate is a separate implementation of the existing `yb_mmr_*` API.
Compile `native_mmr_prepared_composer.c` instead of `native_mmr_composer.c`, never
both together. It uses the same header, frame guards and arithmetic. The
published baseline, default build and Kodi playback remain unchanged.

The owned frame plan prepares two exact tables per channel: the segment index
selected by each original whole input code, and that code clamped to the
channel's metadata endpoints. Segment choice is explicitly made before
clamping. All input codes are validated before accessing tables. The existing
mapping arithmetic, signed floors, residual lookup, wide fallback and output
rounding are unchanged. Tables cover the full accepted 8/10-bit domains and
are rebuilt when metadata changes. There is no image-dependent approximation,
display-dependent limit or three-dimensional colour lookup table.

The candidate plan is 46,064 bytes, versus 36,848 for the previous implementation
in this build: 9,216 additional bytes. Preparation remains inside timings.

## Completed VM checkpoint

[Aggregate evidence](results/native-mmr-prepared-vm-20261005a.json) records an
actual 3840x2160 whole-code run. All 49,766,400 intermediate values across
191 dispatches matched the unchanged reference before timing. Candidate wall
times were 240.547, 237.594 and 239.543 ms; paired unchanged reference times
were 589.518, 592.729 and 588.764 ms. Median candidate time was 239.543 ms,
about 59.4% less time than this run's reference median. Preparation took
0.656–0.734 ms and was included.

The earlier prepared-MMR implementation measured 258.599 ms in a separate
cohort. This candidate's 239.543 ms is promising, but the two optimized backends
were not paired directly in this run, so the historical difference is not a
controlled old-versus-new speed claim. The component profiling run was
instrumented and must not be used as that baseline either.

The retained pre-exit cgroup peak was 57,368,576 bytes under a 512 MiB/no-swap
limit. There were zero high/max/OOM/OOM-kill events and zero swap. Input,
executable, wrapper and runtime library hashes matched before/after the run.
Kodi remained active. CPU quota controller data was unavailable. The peak
snapshot is not final lifetime peak, process RSS or GPU memory.

The benchmark uses the unchanged paired diagnostic, with only the linked
composer changed. Timed checks cover the last chunk; full-frame comparison
precedes timings. Loading, GPU scaling, decoding, colour conversion and display
are excluded. This is not playback FPS or independent Dolby conformance.
Movie data, instruction coefficients, private paths and input hashes are not
published.

## Build and test

Use the strict build command in NATIVE_MMR_COMPOSER.md, substituting only the
composer source and a distinct output executable name. The benchmark is
unchanged and keeps its existing schema; the report identifies the candidate.

```sh
python3 -m unittest discover -s tools/yblod/reference -p 'test_native_mmr_prepared_composer.py'
```

The 17 inherited independent tests compare all four stages with unchanged C
and Python equations, including full code domains, interior pivots, clamped
endpoints, mixed mapping methods, maximum coefficients, wide accumulation,
metadata ownership and rejection guards. Normal and undefined-behaviour
builds both passed. Python is only test orchestration; the candidate is C.
