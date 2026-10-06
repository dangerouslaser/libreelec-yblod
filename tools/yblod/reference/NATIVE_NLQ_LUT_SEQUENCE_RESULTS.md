# Native NLQ lookup table sequence results

The exact NLQ lookup table passed output and synthetic metadata-transition
checks, but its timing improvement was not consistent across these two frames.
Keep it experimental: one frame improved by 22.96%, while a slow repeat on the
other produced a 30.82% pooled regression. These are resident-input host wall
times, not GPU kernel measurements or full-player playback results.

## Before and after timing

On 2026-10-06, each input frame ran original arithmetic, lookup table, lookup
table, original arithmetic in ABBA order. Each run used eight warmups and twelve
timed samples. Each balanced comparison pools 24 samples per mode.

| Frame | Original wall median ms | Lookup wall median ms | Wall change | Original process CPU median ms | Lookup process CPU median ms | CPU change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1943 | 8.945876 | 6.891888 | -22.9602% | 0.294883 | 0.318966 | +8.1672% |
| 1960 | 8.997899 | 11.771331 | +30.8231% | 0.281501 | 0.183140 | -34.9417% |

| Frame and run | Mode | Wall median ms | Wall range ms | Process CPU median ms |
| --- | --- | ---: | --- | ---: |
| 1943 first | Original | 8.924940 | 8.463078 to 9.506446 | 0.306438 |
| 1943 second | Lookup | 6.947432 | 6.664084 to 7.254903 | 0.341320 |
| 1943 third | Lookup | 6.862200 | 6.493683 to 7.164173 | 0.242957 |
| 1943 fourth | Original | 8.959498 | 8.506304 to 9.582957 | 0.284959 |
| 1960 first | Original | 8.997899 | 8.468692 to 9.525887 | 0.182791 |
| 1960 second | Lookup | 6.655660 | 6.431583 to 7.030008 | 0.160739 |
| 1960 third | Lookup | 16.835679 | 16.512653 to 17.289773 | 0.250468 |
| 1960 fourth | Original | 9.031024 | 8.567939 to 9.670470 | 0.331358 |

The second lookup run for frame 1960 was slow across all twelve samples, not
just one outlier. Its cgroup recorded no CPU quota throttling. The reason is
not established; retain all samples and repeat the balanced test before making
a playback performance decision. The stable original endpoints and improvement
on frame 1943 do not justify discarding this regression or combining the frames
into a headline speedup.

## Accuracy and cache checks

All eight guarded runs completed with cleanup and controller exit status zero.
Each checked three full-frame CPU oracles across a synthetic NLQ-offset A/B/A
sequence, comparing 37,324,800 reconstructed values per run. Restoring A was
bit-exact over 12,441,600 values. Original-A output hashes were identical between
lookup and arithmetic modes for each frame, verified privately.

Each lookup run performed three table builds and uploads, with eighteen cache
hits. Each table contains 3,072 exact int32 values and occupies 12,288 bytes.
The numerical NLQ metadata change invalidated the cached table, and returning
to A restored the original output. Original arithmetic performed no table builds
or uploads. No clipping or precision policy changed.

Against the native integer CPU composer, luma was exact and all chroma differences
were at most one output code value in both modes, including the synthetic
metadata states. Lookup-mode equivalence does not make the FP32 composer
bit-exact against the CPU composer, nor establish licensed Dolby conformance.

There were 298,598,400 CPU-oracle value comparisons in total, but only **two
unique input frames**, reused across modes and synthetic metadata states.
These are not eight independent accuracy frames or real-media RPU transitions.

## Resource checks and scope

Input and executable identities, driver artifacts, idle-player state, and Kodi
process identity were unchanged across each guarded run. FP32 reconstruction
was selected with no integer fallback, shader compilation failure, or generation
failure. Device-binding and GL/EGL error checks passed.

Each standalone probe was limited to one CPU core and 512 MiB memory, with no
swap. The maximum observed cgroup peak was 275.15 MiB. All memory-event counters
were zero. One frame 1943 lookup run recorded four quota-throttled periods and
100.099 ms total throttling over the entire probe; the other seven recorded zero.
This counter covers setup and oracle checks too, not just timed samples.

Timed passes used resident input textures, three full-plane dispatches, one
completion wait, and a four-byte error flag readback. They excluded per-new-frame
preparation/upload and full-image readback. CPU uses CLOCK_PROCESS_CPUTIME_ID,
covering all diagnostic process threads, not one thread or whole-player CPU.
Host submit/finish wall time is not isolated GPU kernel time. The probe
uploaded its saved input planes rather than exercising VA-API zero-copy import.
Kodi remained idle during this matrix; no playback throughput or HDMI presentation
claim follows from these results.

Exact scalar samples, per-run ranges, oracle metrics, and resource counters are
available in the [machine-readable results](NATIVE_NLQ_LUT_SEQUENCE_RESULTS.json).

The [original metadata repeat](NATIVE_NLQ_LUT_REPEAT_RESULTS.md) retained this
matrix and found another slow lookup run on the other frame. A repeatable overall
timing gain is still not established.
