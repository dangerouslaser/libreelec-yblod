# Native NLQ lookup table longer warmup results

With 32 warmups and 32 timed samples per run, lookup-table resident-input wall
time improved by 27.26% and 25.58% on the two saved frames. All four lookup runs
stayed in the fast timing range. Earlier slow lookup runs remain part of the
evidence: this matrix supports further opt-in testing, not a proven fix for
timing variability or a full-player speedup.

## Before and after timing

The 2026-10-06 matrix used original metadata and ABBA ordering separately for
each frame. Each balanced comparison pools 64 samples per mode. CPU measurements
use CLOCK_PROCESS_CPUTIME_ID across all diagnostic process threads, not calling
thread CPU or whole Kodi CPU.

| Frame | Original wall median ms | Lookup wall median ms | Wall change | Original process CPU median ms | Lookup process CPU median ms | CPU change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1943 | 9.283081 | 6.752131 | -27.2641% | 0.282255 | 0.305379 | +8.1926% |
| 1960 | 8.956665 | 6.665214 | -25.5838% | 0.205439 | 0.303768 | +47.8632% |

| Frame and run | Mode | Wall median ms | Wall range ms | Process CPU median ms |
| --- | --- | ---: | --- | ---: |
| 1943 first | Original | 9.428626 | 8.502563 to 26.205270 | 0.282255 |
| 1943 second | Lookup | 6.819672 | 6.406999 to 7.223280 | 0.335470 |
| 1943 third | Lookup | 6.648158 | 6.356966 to 7.097840 | 0.161462 |
| 1943 fourth | Original | 8.972781 | 8.375690 to 9.650906 | 0.282409 |
| 1960 first | Original | 8.776062 | 8.302978 to 9.559921 | 0.167410 |
| 1960 second | Lookup | 6.622650 | 6.349829 to 7.021653 | 0.290095 |
| 1960 third | Lookup | 6.705047 | 6.470107 to 7.148907 | 0.313902 |
| 1960 fourth | Original | 9.126910 | 8.356500 to 11.510572 | 0.306870 |

The original frame 1943 first run reached 26.205270 ms; those samples are retained.
Lookup medians stayed between 6.622650 and 6.819672 ms, but process CPU medians
were variable and did not show a consistent CPU saving. Host submit/finish wall
time includes completion waits and is not isolated GPU kernel time. Inputs were
resident uploaded textures; new-frame preparation/upload and full-image readback
were excluded. This did not exercise VA-API zero-copy import or active playback.

## Earlier slow runs remain unresolved

The [initial synthetic metadata matrix](NATIVE_NLQ_LUT_SEQUENCE_RESULTS.md) had
a 16.835679 ms lookup median on frame 1960. The
[original metadata repeat](NATIVE_NLQ_LUT_REPEAT_RESULTS.md) had a 16.810474 ms
lookup median on frame 1943. Neither slow run recorded cgroup quota throttling.
No comparable slow lookup samples appeared in this longer-warmup matrix, but
increased warmup has not been shown to cause their disappearance. Do not discard
the earlier runs or merge all matrices into one claimed speedup.

## Accuracy and resource checks

All eight runs completed with clean teardown, unchanged input/executable/driver
identities, stable idle Kodi identity, and controller exit status zero. Each
accepted 65 FP32 reconstructions, zero integer reconstructions, one shader-cache
miss and 64 shader-cache hits, with no shader or generation failures.
Each lookup run built and uploaded one exact NLQ table and recorded 64 table
cache hits. No metadata changes were exercised in this matrix.

Each run compared 12,441,600 reconstructed values against the native integer CPU
composer. Luma was exact; chroma differences were at most one output code in both
modes. Original outputs matched exactly between modes, checked privately. The
matrix adds 99,532,800 comparisons; all three matrices total 497,664,000 repeated
comparisons over **two unique input frames**, not 24 independent frames or real
metadata-transition scenes. These checks do not establish Dolby conformance.

Each probe used a one-core quota and 512 MiB memory cap with no swap. Peak memory
was at most 251.70 MiB. All memory events and quota-throttling counters were zero.
Kodi remained idle throughout the matrix. The next useful qualification is
broader opt-in testing, including real playback and metadata changes, with the
previous timing branches preserved for diagnosis.

The [scalar results](NATIVE_NLQ_LUT_LONGER_WARMUP_RESULTS.json) include all samples,
per-run medians/ranges, accuracy metrics, route counts, and resource guards.
