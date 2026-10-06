# FP32 playback comparison — completed ABBA checkpoint

The selectable hybrid composer now works during actual 1917 playback, not only
standalone testing. The exact same installed Kodi binary was used; only the
FP32 selection environment setting changed.

| Run | Composer wait per released transaction | Drops / skips added in logged ~10–70 s window |
|---|---:|---:|
| Integer A1 | 16.84 ms | 9 / 12 |
| FP32 B1 | 9.23 ms | 0 / 0 |
| FP32 B2 | 9.26 ms | 0 / 0 |
| Integer A2, reverse control | 16.42 ms | 3 / 4 |

That is approximately 44–45% less composer waiting across the repeated integer
and FP32 controls. Stage measurements subtract cumulative totals from
release 120 to the last complete log, not averages of cumulative averages.
They are host-observed helper wall times, not exclusive GPU kernel timings or
a complete end-to-end frame budget. The stage windows finish at different
released counts; released transactions must not be interpreted as unique
video frames or display flips. Reverse-order integer control reproduced the
slower composer timing rather than erasing the improvement.

B2 had one startup skip before the measured interval; its zero delta is **not**
a whole-playback zero-skip claim. All four observed runs stayed at normal
speed without stalls or failure markers. FP32 logs explicitly confirmed the
hybrid route with zero integer fallback or generator/compiler failures.

Two separate real-frame accuracy checks compared 24.88 million reconstructed
codes: 99.9148% exact, identical luma, remaining chroma differences no larger
than one 12-bit code. This compares our native integer reference, not a
licensed player or TV capture. It does not imply whole-film accuracy coverage.
The integer GPU route matched the CPU reference exactly across those same two
frames, so the baseline comparison is independently checked rather than assumed.

All 12 public synthetic cases completed successfully: MMR orders 1–3, output
depths 10/12, and default/small enhancement-correction parameters. Of 73,728
codes, only two differed from the CPU integer reference, each by one code.
The actual GPU topology sequence order3 → order1 → order3 used one wrapper
handle, two cache misses and five hits, with zero integer fallback. Returning
to the first topology restored all three output planes exactly. An earlier
order3 → order3 numerical-only change is not used as topology-change evidence.

Whole-service memory snapshots were approximately 1.7–1.8 GB during playback
and are retained in the JSON. The 512 MB cap applies to isolated diagnostics,
not these Kodi playback runs. These snapshots are not
engine-only allocations or comparable per-run peaks; B2 shares B1's process
and cumulative high-water history. No claim of a memory reduction is made.

The service-shutdown heap corruption was reproduced and remains a separate
roadblock. Successful player stop does not qualify service shutdown.

## Reproduction tools

The actual wrapper comparison and sequence probe sources are in
`engine/experimental/native_gpu_composer_fp32_*_probe.c`. The SDK recipe is
`tools/yblod/reference/build_fp32_wrapper_diagnostic.sh`; run it inside an
externally memory/CPU-limited container, supplying engine, probe-source, and
fresh output directories.

`observe_native_1917.py` is the exact lab playback observer. It assumes the
test VM's local Kodi JSON-RPC configuration and movie ID 51 identifies 1917;
verify/adapt that ID before using it with another library. It starts playback,
requires a pinned binary SHA and fresh report path, and can stop playback on
completion. Treat its raw reports as private; the published parser extracts
the scalar performance evidence. Parser tests are in
`test_playback_comparison.py`.
