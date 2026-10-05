# GPU timer driver audit

Ordinary `GL_TIME_ELAPSED` queries produced implausibly small totals while
complete four-stage reconstruction checks still passed. Do not use those
numbers as shader throughput or evidence that GPU processing is almost free.

## Inspected source

The local LibreELEC SDK build contains Mesa 26.2.4. Read-only inspection of its
Iris sources found this likely explanation:

- `iris_query.c`, lines 438–444: only compute-invocation statistics queries are
  assigned to the compute batch; elapsed-time queries use the render batch.
- `iris_query.c`, lines 194–200: elapsed-time timestamp writes explicitly use
  the render batch. Query begin/end, lines 485–584, write query snapshots and
  attach availability to that batch.
- `iris_draw.c`, lines 394–445: compute dispatch uses the separate compute
  batch.
- `iris_pipe_control.c`, lines 376–416: memory barriers flush active batches
  separately; this path does not insert a compute-completion dependency into
  the render timer markers.

Therefore the ordinary query may bracket render-engine markers without
bracketing the compute work. This is a source-based inference consistent with
the measurements, **not proof of the exact loaded VM driver's implementation**.
The SDK source hashes below identify inspected files, not a source-to-loaded-
binary attestation. The [upstream Mesa repository](https://gitlab.freedesktop.org/mesa/mesa)
provides source context; no claim is made that a remote tag is byte-identical
to the local SDK tree.

All paths below are relative to the inspected Mesa source root:

| Path | SHA256 |
| --- | --- |
| `src/gallium/drivers/iris/iris_query.c` | `b543decc3c55ee1f01cdce3d15504752580d061c021a9d39b42288ebb1da734e` |
| `src/gallium/drivers/iris/iris_draw.c` | `2db0f8123ea073556ba367668e1491c52418ed1b6c653be9eb83e887a1a84727` |
| `src/gallium/drivers/iris/iris_pipe_control.c` | `93a760464e6380e5807e1bb5c024bb1326bd2821ad662e155b62b00a1f11cf0d` |
| `src/gallium/drivers/iris/iris_fence.c` | `3b7acbbb0149c8be2beabafac030ad79b35633216e19bbbf162df00c46c8945a` |

## Chronological control

The separate query-control experiment explicitly waits for three milestones:
the query start marker before compute submission; compute completion before
the query end marker; and the end marker before reading the available result.
Local `iris_fence.c` inspection supports that ordering: lines 246–286 flush or
capture fences across batches, while lines 410–434 handle deferred submission
and gather each engine's outstanding synchronization handles.

This is an intentionally host-synchronized, cross-batch chronological
bracket. Its interval includes submission gaps, waiting and possible idle or
preemption time. It is **not exclusive kernel/ALU busy time**, and it does not
prove a whole frame is GPU-resident. Upload/readback still occur in 48 batches.
Correctness remains separately gated by complete four-stage comparisons.

## Timer safety and interpretation

The [Khronos ARB_timer_query specification](https://registry.khronos.org/OpenGL/extensions/ARB/ARB_timer_query.txt)
defines completion-based elapsed intervals. It makes overflow undefined,
allows narrow counters, and warns that context switching and other system
effects can affect results. The diagnostic requires a 33–64-bit counter, a
positive result no greater than five seconds, checked aggregation, and a
host-observed interval no greater than five seconds. A fence wait timeout alone
would not bound host preemption before that wait starts.

Results are requested as 64-bit values only after availability is true. Failed
waits, unavailable results, arithmetic bounds or cleanup fail the diagnostic;
they cannot become successful performance evidence. Host wall time, process
CPU time and query elapsed time are distinct observations: subtracting CPU
time from wall time does not isolate GPU execution time.

No driver, Kodi, display or TV settings were changed for this source audit.
