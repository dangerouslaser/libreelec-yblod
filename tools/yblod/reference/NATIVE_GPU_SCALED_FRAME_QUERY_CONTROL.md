# Explicit query-order synchronization control

`engine/experimental/native_gpu_scaled_frame_query_control.c` is a separate
diagnostic for the unexpectedly small elapsed-query readings from the device
probe. It leaves that probe, the integer shader and the arithmetic contract
unchanged. It is not a performance optimization or a Kodi playback change.

The intended control establishes three explicit completion boundaries: begin
the elapsed query and wait for its start fence before dispatch; wait for compute
completion before ending the query; then wait for the query-end completion
fence before checking availability and retrieving its result. Each wait is
finite. The preloaded input completion and bounded readback are retained.

These additional synchronization points deliberately change the workload.
Device elapsed values may now include host submission gaps and idle time
between completed query boundaries. A larger reading would not prove exclusive
shader busy time or establish a production speed regression. Unchanged tiny
readings would not establish that computation itself is fast. Compare the
observations only to qualify query coverage and ordering on the tested driver.

Full-frame four-stage exactness remains the independent arithmetic gate.
Counter-width, availability-before-result, overflow, finite-wait and cleanup
guards remain required. `--validate` and `YB_GPU_PROBE_HOST_ONLY` execute no GPU
work and must report no device timing attempt, zero query counts and no device
elapsed array. The synthetic test subclass reuses the arithmetic, batch,
suffix, malformed-input and actual counter-helper tests, with separate
structural guards for this control's synchronization order.

An execution marked `complete` does not by itself qualify timer accuracy.
Any public hardware checkpoint must preserve that distinction and report
source identity, exactness, all elapsed/host timings, query counts, resource
limits and cleanup. The underlying driver's timer coverage is still an open
question until this control and driver review are interpreted together.

Build with the device probe's dependencies and flags, replacing only its main
C file with `native_gpu_scaled_frame_query_control.c`; CLI arguments remain
unchanged. This is not whole-frame-resident rendering, fractional Y416
processing, real-time throughput or Dolby display conformance.

## Completed control checkpoint

The [combined source-pinned result](results/native-gpu-query-control-vm-20261005e.json)
preserves both untrusted original elapsed readings and these synchronized
control runs. Both real control frames passed all 49,766,400 stage comparisons
through 48 GPU batches and 191 CPU oracle subchunks. Each measured pass returned
48 query results with a 64-bit elapsed counter.

| Prepared frame | Device elapsed, three passes (ms) | Host dispatch/wait, three passes (ms) | Complete frame, three passes (ms) |
|---|---|---|---|
| 2296 | 301.5, 286.9, 460.4 | 316.3, 302.0, 480.9 | 528.4, 476.2, 721.1 |
| 1406 | 286.1, 163.4, 185.7 | 303.8, 174.5, 196.9 | 474.0, 336.8, 379.8 |

Maximum charged control memory was 121,421,824 bytes (115.80 MiB), below the
512 MiB ceiling. Job swap and memory-limit/OOM events were zero; Kodi remained
unchanged. This accounting does not bound every GPU/system allocation.

The synchronized intervals are hundreds of milliseconds rather than the
unbracketed probe's microsecond sums. The control establishes explicit
chronological boundaries around the work, but adds waits and CPU submission
gaps inside those boundaries. It does not isolate exclusive shader execution,
prove timer accuracy universally or support a direct speed comparison with
the differently instrumented original runs. The original readings remain
untrusted as compute-performance evidence.

The [Mesa timer/compute source audit](NATIVE_GPU_TIMER_DRIVER_AUDIT.md) explains
why this ordering control was selected. It is an inference from reviewed SDK
source, not authentication of the driver actually loaded on the VM or proof
of exclusive GPU busy time.

The next arithmetic experiment is an exact metadata-derived enhancement
correction table: 1,024 entries per component, 3,072 signed 32-bit values
(12 KiB) in total. It targets repeated calculations without changing their
results; it is not a fitted colour adjustment or an SK4-matching policy. Any
candidate must pass the independent complete-stage gates and a clearly scoped
performance comparison before adoption. Kodi integration still waits.
