# Native NLQ lookup table restored active Kodi repeat

Long lookup waits returned after restoring idle Kodi. Despite better pooled
medians, lookup mean wall time was about 18% worse on both saved frames.
Keep the option experimental. The active/stopped/active pattern supports further
investigation of competing GPU work or scheduling, but does not prove that GUI
rendering caused the delays or predict active-playback performance.

## Before and after timing

The 2026-10-06 repeat used the same instrumented probe and mathematical inputs,
32 warmups and 32 timed samples per run, original metadata, and per-frame ABBA
order. Balanced comparisons pool 64 samples per mode; no samples are discarded.

| Frame | Original median ms | Lookup median ms | Median change | Original mean ms | Lookup mean ms | Mean change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1943 | 8.997234 | 7.019982 | -21.9762% | 8.976998 | 10.631917 | +18.4351% |
| 1960 | 9.065244 | 7.042185 | -22.3167% | 8.919639 | 10.589547 | +18.7217% |

| Frame and run | Mode | Wall median ms | Wall range ms | Process CPU median ms | Samples above 10 ms |
| --- | --- | ---: | --- | ---: | ---: |
| 1943 first | Original | 9.098640 | 8.478296 to 9.708088 | 0.326241 | 0 |
| 1943 second | Lookup | 6.729758 | 6.362851 to 7.163778 | 0.307854 | 0 |
| 1943 third | Lookup | 15.365757 | 6.493774 to 24.511021 | 0.279853 | 26 |
| 1943 fourth | Original | 8.925181 | 8.355382 to 9.533211 | 0.215650 | 0 |
| 1960 first | Original | 8.876823 | 8.340832 to 9.644126 | 0.279807 | 0 |
| 1960 second | Lookup | 15.258252 | 6.433851 to 16.911795 | 0.264781 | 28 |
| 1960 third | Lookup | 6.738310 | 6.297947 to 7.184324 | 0.304591 | 0 |
| 1960 fourth | Original | 9.075738 | 8.369111 to 9.585133 | 0.284445 | 0 |

The [preceding stopped-Kodi matrix](NATIVE_NLQ_LUT_INACTIVE_RESULTS.md) had no
sample above 10 ms, with all lookup samples below 7.36 ms. In this restored-active
repeat, 54 of 128 lookup samples exceeded 10 ms, while every original sample
remained below 10 ms. Original medians stayed near 9 ms in both states. The
reappearance is meaningful diagnostic evidence, but sequential blocks leave
order, power, driver scheduling, and other system activity as possible factors.
These tests do not establish exclusive GPU ownership in either state.

## Frequency and environment scope

Every run verified frequency device binding and collected 32 before/after actual
and requested endpoint readings per field. All readings were available; zero
actual readings are retained, not treated as missing. Endpoints are not
time-weighted or kernel-exclusive execution frequencies. Sysfs reads may perturb
power or scheduling, and do not isolate the cause of long waits.

The operator checked the systemd manager environment during this repeat and found
no INTEL_DEBUG, INTEL_SIMD_DEBUG, MESA-prefixed, LIBGL_ALWAYS_SOFTWARE, LD_PRELOAD,
or LD_LIBRARY_PATH overrides. This narrow external check is not a complete
per-probe inherited-environment fingerprint and is not claimed as a guard property.

CPU timing uses CLOCK_PROCESS_CPUTIME_ID across all diagnostic process threads,
not calling-thread or whole-player CPU. Timed host submission and completion waits
exclude new-frame preparation/upload and full-image readback; they are not
exclusive GPU kernel or playback frame timings. Uploaded resident planes did not
exercise VA-API zero-copy import.

## Accuracy and resource qualification

All eight runs passed artifact/configuration guards, unchanged active Kodi
process identity, idle-player checks, device/GL/EGL checks, and cleanup. Original
outputs matched exactly across modes and matched retained uninstrumented outputs
privately. Each run checked 12,441,600 values against the native integer CPU
composer: exact luma, chroma differences at most one code, unchanged by lookup mode.

Each accepted 65 FP32 reconstructions, zero integer reconstructions, one shader
cache miss and 64 hits; lookup runs built/uploaded one exact table and recorded
64 table hits. No metadata transitions were exercised. The same two saved frames
were reused, so eight runs are not eight independent accuracy frames or Dolby
conformance evidence.

The standalone probes used a one-core quota and 512 MiB cap with no swap. Peak
memory was at most 251.63 MiB. All memory-event and quota-throttling counters were
zero. Kodi was active but idle, not playing video. Actual playback validation
and further scheduling diagnosis remain necessary before enabling this option
by default.

The [scalar results](NATIVE_NLQ_LUT_ACTIVE_REPEAT_RESULTS.json) retain all timing
and frequency samples. The [first active frequency matrix](NATIVE_NLQ_LUT_FREQUENCY_RESULTS.md)
and [stopped-Kodi comparison](NATIVE_NLQ_LUT_INACTIVE_RESULTS.md) remain separate
so their long waits and scope are preserved.
