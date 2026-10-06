# Native NLQ lookup table frequency observations

Frequency endpoint sampling did not explain the intermittent long lookup-table
waits. Median wall time improved on both frames, but one lookup run contained
twelve long samples and made the frame 1943 pooled mean **7.89% slower**. Keep
the option experimental and retain both fast and slow samples.

## Before and after timing

The 2026-10-06 original-metadata ABBA matrix used 32 warmups and 32 samples per
run. Balanced comparisons pool 64 samples per mode. Timings are resident-input
host submit/finish wall time, not GPU kernel or playback frame time.

| Frame | Original median ms | Lookup median ms | Median change | Original mean ms | Lookup mean ms | Mean change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1943 | 8.913347 | 6.723402 | -24.5693% | 8.962506 | 9.669936 | +7.8932% |
| 1960 | 8.908767 | 6.751307 | -24.2173% | 8.991263 | 6.767716 | -24.7301% |

| Frame and run | Mode | Wall median ms | Wall range ms | Process CPU median ms |
| --- | --- | ---: | --- | ---: |
| 1943 first | Original | 8.913347 | 8.274402 to 9.905316 | 0.254857 |
| 1943 second | Lookup | 7.006187 | 6.431323 to 23.212371 | 0.296631 |
| 1943 third | Lookup | 6.654921 | 6.274516 to 6.974209 | 0.202270 |
| 1943 fourth | Original | 8.909273 | 8.461056 to 9.649312 | 0.262513 |
| 1960 first | Original | 8.911620 | 8.424554 to 9.631277 | 0.323157 |
| 1960 second | Lookup | 6.699507 | 6.313551 to 7.579899 | 0.189138 |
| 1960 third | Lookup | 6.776055 | 6.511384 to 7.195304 | 0.332242 |
| 1960 fourth | Original | 8.885349 | 8.422269 to 9.501122 | 0.282668 |

The first frame 1943 lookup run contained twelve samples from 22.399407 to
23.212371 ms. Its mean was 12.731076 ms, despite a 7.006187 ms median. All samples
are retained. No cgroup CPU quota throttling was recorded. Diagnostic process
CPU uses CLOCK_PROCESS_CPUTIME_ID across all process threads, not calling-thread
or whole-player CPU.

## Actual and requested frequency endpoints

Read-only i915 actual and requested MHz readings were collected immediately
before and after each timed submission, outside the host timing clocks. The
device binding was verified for every run. Each of the four reading fields had
32 samples per run: **1,024 readings in total, zero unavailable minus-one values**.
Zero actual-MHz readings are reported values, not missing reads.

| Frame and run | Actual before range MHz | Actual after range MHz | Requested before range MHz | Requested after range MHz | Actual zero readings before and after |
| --- | --- | --- | --- | --- | --- |
| 1943 first | 0 to 1300 | 0 to 1300 | 1267 to 1300 | 1267 to 1300 | 3 and 4 |
| 1943 second | 0 to 1300 | 0 to 1300 | 1267 to 1300 | 1267 to 1300 | 2 and 2 |
| 1943 third | 1300 | 1300 | 1300 | 1300 | 0 and 0 |
| 1943 fourth | 0 to 1300 | 0 to 1300 | 1267 to 1300 | 1283 to 1300 | 18 and 17 |
| 1960 first | 0 to 1300 | 0 to 1300 | 1267 to 1300 | 1267 to 1300 | 27 and 29 |
| 1960 second | 0 to 1300 | 0 to 1300 | 1283 to 1300 | 1300 | 28 and 28 |
| 1960 third | 0 | 0 | 1300 | 1300 | 32 and 32 |
| 1960 fourth | 0 to 1300 | 0 to 1300 | 1267 to 1300 | 1267 to 1300 | 9 and 10 |

Several long samples had actual and requested readings of 1300 MHz at both
endpoints. Conversely, the fast frame 1960 third run reported actual zero at
every endpoint while requested frequency stayed at 1300 MHz. These observations
are not time-weighted execution frequencies and do not establish throttling,
its absence during a kernel, or the cause of long waits. Sampling sysfs may
itself perturb scheduling or power behavior; the instrumented and earlier
uninstrumented timings are not interchangeable.

## Accuracy and resource checks

All eight guards, cleanup checks, and the controller completed successfully.
Cross-mode original outputs were identical for each frame. They also matched
the retained uninstrumented original-output hashes privately, confirming that
the collector did not change the tested output. Input/executable/driver identities
and idle Kodi identity stayed unchanged within every run.

Each run accepted 65 FP32 reconstructions, zero integer reconstructions, one
shader-cache miss and 64 shader-cache hits. Lookup runs built/uploaded one exact
table and recorded 64 table hits. One full-frame CPU oracle compared 12,441,600
values per run: exact luma and chroma differences at most one code against the
native integer CPU composer, unchanged by lookup mode. This adds 99,532,800
comparisons over the same two unique saved input frames, not new independent
frames or Dolby conformance evidence.

Each standalone probe used a one-core quota and 512 MiB cap with no swap. Peak
memory was at most 250.61 MiB. All memory-event and quota-throttling counters
were zero. Kodi stayed idle; this did not test active playback or VA-API zero-copy
input import. Per-frame input preparation/upload and full-image readback were
excluded from timed passes.

The [frequency scalar results](NATIVE_NLQ_LUT_FREQUENCY_RESULTS.json) retain all
timing/frequency samples and missing-read counts. The
[longer warmup results](NATIVE_NLQ_LUT_LONGER_WARMUP_RESULTS.md),
[original metadata repeat](NATIVE_NLQ_LUT_REPEAT_RESULTS.md), and
[synthetic metadata results](NATIVE_NLQ_LUT_SEQUENCE_RESULTS.md) preserve the
earlier fast and slow branches separately.
