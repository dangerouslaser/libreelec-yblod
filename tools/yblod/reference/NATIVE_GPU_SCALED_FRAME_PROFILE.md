# Instrumented full-frame GPU path profile

`engine/experimental/native_gpu_scaled_frame_profile.c` is an isolated copy of
the full-frame probe with host monotonic phase clocks. The tested probe and
integer shader are unchanged. It retains the complete CPU gate, full-frame
four-stage GPU comparison, width rejection before dispatch, private context,
bounded buffers, finite waits and cleanup checks.

The [public result](results/native-gpu-scaled-frame-profile-libreelec-20261005a.json)
records a completed Intel P010 prepared-input diagnostic. Every one of
49,766,400 stage values matched exactly across 191 chunks. One warmup preceded
three timed passes; only the final chunk is cross-checked during timing, after
the untimed complete-frame gate. This is not Kodi playback or a Dolby display
accuracy result.

## What the clocks include

Four arrays record accumulated chunk intervals for each timed pass:

| Field | Included work |
|---|---|
| `extract_pack_wall_ns` | Scaled P010 extraction, sample packing, output sentinel initialization and metadata packing |
| `upload_wall_ns` | Metadata, input and sentinel buffer updates, binding and error checks |
| `dispatch_barrier_fence_wait_wall_ns` | Dispatch, memory barrier, fence creation, finite client wait, error checks and fence deletion |
| `readback_wall_ns` | Binding, bounded four-stage readback and error checks |

These are **host-observed wall intervals**, not GPU device timestamp queries.
Asynchronous driver work can be paid during a later interval. In particular,
the dispatch/wait interval is not an isolated shader kernel measurement.
Instrumentation itself has overhead; comparisons with uninstrumented runs
are not a direct paired speed test. Each phase accumulator is overflow checked,
and the sum must not exceed the measured total frame interval.

## Measured checkpoint

| Interval | Three observed passes, milliseconds |
|---|---|
| Complete warm frame | 824.0, 784.9, 634.3 |
| Process CPU time | 218.4, 232.4, 261.2 |
| Extraction and packing | 154.9, 162.2, 171.8 |
| Upload and binding | 30.1, 35.3, 46.8 |
| Dispatch, barrier and fence wait | 624.2, 573.1, 402.4 |
| Readback | 14.6, 14.3, 13.2 |

Cold setup was 24.3 ms and teardown 2.9 ms, outside the warm-frame intervals.
Dispatch plus synchronization was the largest host interval in every pass.
This does not identify whether shader arithmetic, driver execution, scheduling
or synchronization is the underlying cause.

The current diagnostic serializes 191 upload/dispatch/wait/readback cycles and
transfers all intermediate outputs. For 12,441,600 samples, its 16-byte input
upload, 16-byte output-sentinel upload and 16-byte diagnostic readback represent
597,196,800 logical API bytes per pass, excluding metadata. This is traffic,
not simultaneously allocated RAM or a measured physical PCIe transfer count.

Peak charged memory was 102,248,448 bytes (97.51 MiB) under a 512 MiB ceiling,
with job swap disabled and zero memory-limit/OOM/swap events. These counters
do not bound all GPU or system allocations. Kodi remained active. Artifact
identities remained unchanged and GL/EGL success plus cleanup were recorded.

## Next gates

Keep this as a diagnostic rather than integrating the slower route into Kodi.
First test a larger GPU batch of 262,144 samples, preserving the CPU oracle's
65,536-sample subchunk bound. The last-batch check must use the correct golden
suffix when GPU and CPU chunk boundaries differ. Then test bounded queueing
and separate host staging costs with explicitly labelled resident-input tests,
while retaining complete exactness and finite waits.
A later GPU-resident final-output path should avoid production readback
of all diagnostic stages, but must first pass the same independent gates.
GPU device timing, surface sharing, fractional Y416 precision and GL/GLES
interoperability remain separate experiments.

Build with the same sources and flags as the full-frame probe, replacing only
`native_gpu_scaled_frame_probe.c` with `native_gpu_scaled_frame_profile.c`.
The CLI is unchanged. `--validate` and `YB_GPU_PROBE_HOST_ONLY` remain strictly
CPU-only; they do not emit hardware phase measurements. Synthetic host tests
and the source-pinned public-result tests do not execute GPU work.
