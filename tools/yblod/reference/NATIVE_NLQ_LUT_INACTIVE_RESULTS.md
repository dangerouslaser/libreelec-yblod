# Native NLQ lookup table tests with Kodi stopped

With Kodi stopped, all four lookup runs stayed below 7.36 ms per timed sample.
The lookup option improved median resident-input wall time by 26.40% and 25.64%
on the two saved frames. The preceding active-idle matrix had twelve long lookup
samples on one run. This comparison warrants another active-idle repeat; it does
not prove that Kodi rendering caused the long waits or that playback will improve.

## Before and after timing

The 2026-10-06 matrix used the same frequency-instrumented probe, numerical
inputs, original metadata, 32 warmups, 32 samples, and per-frame ABBA order as
the preceding active-idle test. Each comparison pools 64 samples per mode.

| Kodi state and frame | Original median ms | Lookup median ms | Lookup change | Original mean ms | Lookup mean ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Active idle 1943 | 8.913347 | 6.723402 | -24.5693% | 8.962506 | 9.669936 |
| Stopped 1943 | 9.001849 | 6.625571 | -26.3977% | 8.950823 | 6.674039 |
| Active idle 1960 | 8.908767 | 6.751307 | -24.2173% | 8.991263 | 6.767716 |
| Stopped 1960 | 9.013297 | 6.701947 | -25.6438% | 9.032469 | 6.719833 |

| Stopped frame and run | Mode | Wall median ms | Wall range ms | Process CPU median ms |
| --- | --- | ---: | --- | ---: |
| 1943 first | Original | 9.023365 | 8.407062 to 9.756783 | 0.171800 |
| 1943 second | Lookup | 6.639277 | 6.250814 to 7.164319 | 0.285429 |
| 1943 third | Lookup | 6.595909 | 6.387197 to 7.043334 | 0.180508 |
| 1943 fourth | Original | 8.896183 | 8.332885 to 9.663363 | 0.293890 |
| 1960 first | Original | 9.003860 | 8.461533 to 9.636402 | 0.316401 |
| 1960 second | Lookup | 6.714270 | 6.303500 to 7.357902 | 0.193777 |
| 1960 third | Lookup | 6.681960 | 6.439584 to 7.079237 | 0.285951 |
| 1960 fourth | Original | 9.013297 | 8.388911 to 9.869533 | 0.279163 |

No stopped-service sample exceeded 10 ms. The preceding active frame 1943 lookup
run had twelve samples from 22.40 to 23.21 ms, making its pooled mean worse despite
a better median. Preserve that run and the earlier slow branches. The matrices
were sequential, not interleaved by Kodi state; order, scheduling, and power
variation remain possible explanations. Stopping Kodi does not establish exclusive
GPU ownership or a causal GUI-contention mechanism.

CPU uses CLOCK_PROCESS_CPUTIME_ID across all diagnostic process threads. Host
submission/completion wall time is not GPU kernel time or player frame time.
Inputs were uploaded resident textures, not VA-API zero-copy imports; new-frame
preparation/upload and full-image readback were excluded from timed samples.

## Frequency and guard checks

All eight runs verified device binding and supplied 32 readings for each actual
and requested before/after field: 1,024 readings, none unavailable. Actual endpoint
readings ranged from 0 to 1300 MHz; requested endpoints ranged from 1250 to
1300 MHz. Zero actual readings are preserved as observations, not missing values.
These endpoints are neither time-weighted nor kernel-exclusive execution
frequencies; sysfs reads may perturb scheduling or power behavior.

Before and after every probe, the service was inactive, MainPID was zero, and
there were no actual Kodi processes. The inactive guard makes no JSON-RPC idle
or process-identity claim. Probe/input/driver identities remained unchanged;
cleanup and all accuracy/resource guards passed.

The controller completed all eight cases with exit status zero and restored Kodi
to an active service successfully. The guard pins the probe configuration and
artifacts, but does not fingerprint every inherited manager environment variable;
complete global-environment equivalence is not established by these checks.

Cross-mode outputs matched exactly and matched retained uninstrumented original
outputs privately. Each run checked 12,441,600 reconstructed values against the
native integer CPU composer, with exact luma and chroma differences at most one
code in both modes. Each accepted 65 FP32 and zero integer reconstructions,
one shader-cache miss and 64 hits. Lookup runs built/uploaded one exact table
and recorded 64 table hits. No metadata changes were exercised.

Each probe used a one-core quota and 512 MiB memory cap. Peak memory was at most
251.03 MiB, with zero memory events, swap, and quota-throttling counters. These
are standalone-probe observations, not whole Kodi memory or playback qualification.

The [scalar results](NATIVE_NLQ_LUT_INACTIVE_RESULTS.json) preserve all samples,
frequency endpoints, guards, and the preceding active comparison. Earlier long
samples remain in the [active frequency results](NATIVE_NLQ_LUT_FREQUENCY_RESULTS.md).
Long waits subsequently returned in the
[restored active repeat](NATIVE_NLQ_LUT_ACTIVE_REPEAT_RESULTS.md); the cause
remains unproven.
