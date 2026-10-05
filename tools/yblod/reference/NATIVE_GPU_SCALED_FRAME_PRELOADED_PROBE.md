# Preloaded-batch dispatch diagnostic

`engine/experimental/native_gpu_scaled_frame_preloaded_probe.c` is an isolated
companion to the larger-batch probe. It retains the same integer shader,
262,144-sample GPU batch bound, 65,536-sample CPU oracle bound, complete
four-stage gates, metadata guards and final CPU-suffix observability check.
The original probes and Kodi playback path are unchanged.

## What is timed

Each batch is extracted, packed and uploaded as before. A new finite fence and
host wait complete the preload before starting a second timer. That timer
covers dispatch, barrier, completion fence and host wait; it ends before the
four-stage readback. The overall frame timer still includes preparation,
uploads, **both** waits and readback. Cold setup and teardown remain separate.

`dispatch_wall_ns` sums those host-observed preloaded dispatch intervals across
48 batches. It is **not GPU device elapsed time or isolated shader kernel
time**. Driver execution, scheduling and host waits remain included. The data
is resident only for the current batch: this is not a whole-frame-resident
experiment. All 48 uploads and diagnostic readbacks still occur every pass.

The extra preload fences change the instrumented workload. These runs must
not be presented as a direct speed improvement over older, separately executed
cohorts. They help narrow what to measure next, not prove a production speedup.

## Completed two-frame checkpoint

The [public source-pinned result](results/native-gpu-scaled-frame-preloaded-vm-20261005c.json)
records two real prepared-frame runs. Each passed all 49,766,400 four-stage
comparisons through 48 GPU batches and 191 CPU oracle subchunks. A complete
untimed frame comparison precedes one warmup and three measured passes. Timed
observability checks cover only the final CPU-sized suffix, explicitly labelled.

| Prepared frame | Complete frame, three passes (ms) | Preloaded dispatch/wait sums, three passes (ms) |
|---|---|---|
| 2296 | 396.5, 694.8, 300.0 | 206.9, 434.6, 138.7 |
| 1406 | 347.0, 490.5, 647.0 | 171.1, 285.0, 415.0 |

Median dispatch/wait sums were 206.9 and 285.0 ms, with an observed range of
138.7–434.6 ms. The substantial variability and host-only clocks prevent a
claim that shader arithmetic itself takes those durations. These results also
do not establish real-time playback, fractional Y416 precision, display colour
accuracy or Dolby conformance.

Maximum charged memory was 121,352,192 bytes (115.73 MiB), under a 512 MiB
ceiling. Job swap and memory-limit/OOM events remained zero. This accounting
does not bound all GPU/system allocations. Kodi remained unchanged.

## Host-only gates and next step

The synthetic host suite reuses batch boundaries, late malformed inputs,
metadata-width distinctions, alias checks and the actual suffix-helper tests.
An offline structural check verifies preload completion before dispatch timing
and timing completion before readback. Host and UBSan runs execute no GPU work;
the structural test is not an independent driver synchronization proof.

Build with the larger-batch probe's sources and flags, replacing only its main
C file with `native_gpu_scaled_frame_preloaded_probe.c`. CLI arguments are
unchanged. `--validate` and `YB_GPU_PROBE_HOST_ONLY` remain CPU-only.

The next gate is a separately reviewed device-elapsed timing diagnostic to
distinguish GPU command work from host-side waiting before tuning arithmetic.
Its query capability, completion, bounded retrieval and timing interpretation
need their own checks. Retain the complete untimed comparison and report host
and device timings separately. These findings do not yet justify Kodi
integration or replacing the faster CPU path.
