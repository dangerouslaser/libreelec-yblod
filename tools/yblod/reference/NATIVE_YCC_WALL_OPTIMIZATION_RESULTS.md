# YCC expansion workgroup and coordinate timing results

Keep the existing **8 by 8 workgroup and original sampling coordinates**.
Larger workgroups were slower or variable. Both coordinate alternatives matched
the complete output oracle, but neither demonstrated a repeatable timing gain.
No production default changed as a result of these experiments.

## Before and after timing

All numbers below are resident-input **host submit/finish wall time**, not
exclusive GPU kernel time or full-player frame time. Each variant pools 24
samples from two runs, with eight warmups and twelve samples per run.
Positive percentage changes mean slower.

| Test | Baseline median ms | Candidate median ms | Median change | Baseline mean ms | Candidate mean ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Workgroups 8 by 8 to 16 by 8 | 5.438014 | 6.012415 | +10.5627% | 5.438893 | 6.063330 |
| Workgroups 8 by 8 to 16 by 16 | 5.438014 | 5.715327 | +5.0995% | 5.438893 | 6.748795 |
| Initial coordinates original to integer | 5.526760 | 5.483146 | -0.7891% | 6.879955 | 5.556194 |
| Initial coordinates original to bit operations | 5.526760 | 5.895535 | +6.6725% | 6.879955 | 5.967999 |
| Confirmatory frame 1943 original to integer | 5.679072 | 5.725892 | +0.8244% | 5.709836 | 5.714218 |
| Confirmatory frame 1960 original to integer | 5.473777 | 5.547907 | +1.3543% | 5.502356 | 5.563191 |

The workgroup and initial-coordinate matrices ran in ABCCBA order. For
workgroups A/B/C were 8 by 8, 16 by 8, and 16 by 16; for coordinates they were
original, integer division/parity, and bit operations. The two confirmatory
frame matrices separately ran original/integer/integer/original.

## Variation and decision

The workgroup baseline's two run medians were 5.365950 and 5.531654 ms, a 3.09%
change. The 16 by 16 medians moved from 5.553423 to 7.953668 ms, a 43.22% change.
These variations do not support selecting a larger group for a reliable win.

The initial coordinate baseline moved from an 8.020979 ms median to 5.494574 ms.
Its long samples are retained, not discarded. That uneven baseline produced an
apparent 19.24% mean improvement for integer coordinates, but the improvement
did not repeat: on frames 1943 and 1960, integer-coordinate pooled medians were
0.82% and 1.35% slower. The small differences remain within observed run variation;
no performance advantage is established. Do not pool the initial and confirmatory
matrices into a single headline speedup.

## Accuracy and resource checks

All 20 accepted runs exited successfully and completed cleanup. Each checked
66,355,200 RGBA float components bit-for-bit against the independent integer/dyadic
oracle over two complete-image checks. Together this is **1,327,104,000 component
comparisons across repeated tests of two saved frames**, not twenty independent
accuracy frames. The candidates introduced no bit differences in these checks.
This verifies YCC expansion, not Dolby reconstruction, metadata interpretation,
SK4 agreement, inherited colour processing, HDMI packing, or displayed accuracy.

The probe binary was identical across all runs. Initial baseline shader contents
matched between the workgroup and coordinate matrices, and the first frame's
saved input was identical across its initial and confirmatory tests. Inputs,
shaders, dependencies, Kodi process/start identity, and idle-player state were
guarded before and after each run. Actual linked workgroup dimensions were checked.

Every run used a 512 MiB memory ceiling, zero permitted swap, and one CPU quota.
The largest scoped memory peak was **241,565,696 bytes, approximately 230.4 MiB**.
All memory event counters remained zero and swap usage was zero. Readback used
at most 61,440 bytes per row; uploads and full-image oracle readback were outside
the measured windows. These diagnostic limits are not the Kodi playback limit.

## Measurement scope and reproduction

Hardware was Intel Tiger Lake GT2, reported as Mesa Intel Iris Xe Graphics,
with desktop GL 4.6 and Mesa 26.2.4. GPU timer queries were explicitly disabled
in all accepted runs. Earlier timer-enabled diagnostics returned invalid zero
results on this compute path; see the
[profiling README and timer limitation](gpu_profiling/README.txt) and
[driver audit](NATIVE_GPU_TIMER_DRIVER_AUDIT.md). Wall time minus process CPU time
does not isolate GPU execution. No GPU-exclusive timing is claimed here.

[Scalar results](NATIVE_YCC_WALL_OPTIMIZATION_RESULTS.json) retain all per-run
wall and CPU sample arrays, means, medians, run drift, exact-output checks, and
resource events. A failed preliminary run without a completed result and a
separate sanity run are not included in these twenty accepted balanced runs.
Private input pixels, fixture hashes, and private paths are excluded.

The public profiling README describes the guarded invocation. Coordinate
candidate sources and workgroup generation are documented in the
[YCC efficiency plan](YCC_GPU_EFFICIENCY_PLAN.md); these are diagnostic tests
and do not replace the [actual playback evidence](PARTIAL_LONG_FP32_PLAYBACK_RESULTS.md).
