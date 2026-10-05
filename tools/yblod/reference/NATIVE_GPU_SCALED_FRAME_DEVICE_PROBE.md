# Device elapsed-query diagnostic

`engine/experimental/native_gpu_scaled_frame_device_probe.c` is an isolated
companion to the preloaded-batch probe. Its integer shader, prepared whole-code
contract, CPU/GPU bounds, full-frame four-stage comparison and suffix check are
unchanged. It is not Kodi integration or a change to Dolby arithmetic.

## Query scope and interpretation

Each batch is uploaded and its preload fence completes before measurement.
An elapsed query then surrounds GPU dispatch and the storage/buffer barrier.
The existing host dispatch/wait timer and complete-frame timer remain separate.
Result retrieval occurs only after finite completion and a positive availability
check. Query objects are reused only after their previous result is consumed
and are ended/deleted on cleanup paths.

The [Khronos timer-query specification](https://registry.khronos.org/OpenGL/extensions/ARB/ARB_timer_query.txt)
defines elapsed results in nanoseconds between command-completion boundaries.
Counter overflow is undefined; a zero-width counter is unusable. Reading a
result before availability may block. Device elapsed time is not exclusive
arithmetic-unit busy time: scheduling and other GPU activity can affect it.

This diagnostic conservatively requires 33–64 counter bits and an observed
host dispatch interval no longer than five seconds. The pure host accumulator
rejects zero/out-of-policy elapsed values, unavailable-width assumptions and
sum overflow without changing its output. A 64-bit retrieval preserves the
reported counter width. These are diagnostic policy gates, not claims that
every graphics implementation provides an identical timer or resolution.

`device_elapsed_ns` sums completed per-batch query results for each measured
pass. `device_query_counts` must account for every batch. Reports also
retain `dispatch_wall_ns`, `dispatch_cpu_ns`, preload waits and complete-frame
times. A host/device difference does not isolate one driver cost automatically.
All 48 uploads and four-stage readbacks still occur for a 4K prepared frame;
this remains preloaded batches, not a whole-frame-resident playback pipeline.

## Host-only verification

The synthetic test subclass preserves the preloaded timing-order guards,
batch boundaries, CPU subchunk bound, actual suffix-helper execution, late
malformed input and metadata-width rejection tests. It also executes the actual
counter accumulator with width, elapsed and overflow boundary cases. Structural
source guards check query order, availability before retrieval and cleanup.
These offline checks are not an EGL mock or a hardware timer correctness proof.

`--validate` and `YB_GPU_PROBE_HOST_ONLY` remain strictly CPU-only. Their reports
say `device_timer_attempted: false`, zero counter width/query counts and omit
`device_elapsed_ns`; no hardware measurement is fabricated from host tests.
Build using the preloaded probe's dependencies and strict flags, replacing only
the main C file with `native_gpu_scaled_frame_device_probe.c`.

An actual device checkpoint requires a separate source-pinned, memory-bounded
run with complete exactness, successful query retrieval, unchanged artifacts
and cleanup. Report host and device intervals together, without claiming a
speed improvement from separately ordered cohorts or treating a timer result
as pure shader arithmetic time. Kodi, fractional Y416 precision and display
accuracy remain outside this diagnostic.

## Initial hardware observation: timer not yet qualified

The initial two real-frame executions passed the complete arithmetic gates.
Each compared 49,766,400 values through 48 GPU batches and 191 CPU oracle
subchunks. The driver reported available results for all 48 measured queries
per pass and a 64-bit elapsed counter, without API errors.

However, summed elapsed values were only approximately 3–14 **microseconds**
for complete frame passes. Those unexpectedly small values have not been
independently qualified as measurements of this reconstruction workload.
Do not use them to claim a fast GPU engine, attribute the larger host waits to
a particular cause, or choose arithmetic optimizations on that basis.

A native `complete` result means the execution, arithmetic and API safety gates
passed; it is not proof that this driver's timer reports the intended work.
Host tests likewise prove only their stated guards. The elapsed-query method
remains experimental pending driver/source review and separately measured
synchronization or timing controls. The tested C source is frozen while that
qualification proceeds; no shader, coefficient or clipping policy was changed
to accommodate the observation.

The [combined device/query-control checkpoint](results/native-gpu-query-control-vm-20261005e.json)
preserves the exact raw device sums instead of accepting them as compute timing:

| Prepared frame | Unbracketed device sums, three passes (nanoseconds) |
|---|---|
| 2296 | 12,636; 3,640; 9,568 |
| 1406 | 3,692; 3,692; 13,572 |

Every measured pass returned 48 available 64-bit query results. Maximum charged
memory for these device-probe cohorts was 121,860,096 bytes (116.21 MiB), with
zero memory-limit/OOM/swap events under the 512 MiB/no-job-swap policy. Kodi was
unchanged. Successful resource and arithmetic checks do not qualify these
unbracketed timer values.

The separate [query-order control](NATIVE_GPU_SCALED_FRAME_QUERY_CONTROL.md)
produced much larger elapsed intervals after adding explicit completion
boundaries. That is evidence of sensitivity to the changed timing workload,
not a direct pure-kernel measurement or proof of one underlying driver cause.

The [Mesa source audit](NATIVE_GPU_TIMER_DRIVER_AUDIT.md) documents a plausible
query/compute ordering explanation from the reviewed SDK source. Its source
pins are review evidence, not proof that the running VM loaded identical
driver bytes. The combined result preserves that distinction.
