# Single completion wait per batch

This isolated runner compares against the reduced-output-transfer runner.
The shader, input extraction/packing/uploads, 262,144-sample batch size,
complete untimed four-stage equality gate and warm final-suffix check are unchanged.
The only synchronization change is removing the separate preload fence/wait.
One finite five-second completion fence/wait after each compute dispatch covers
its ordered uploads and computation; no unsynchronized mapped memory is used.

The driver may still block inside upload calls. This experiment does not prove
overlap or asynchronous transfer. The dispatch host interval may include pending
upload work and is explicitly not preloaded kernel time. Whole-pass timing
retains preparation, upload API calls, completion waits and the final suffix
readback. Zero preload timing is a removed phase, not a zero-cost upload.

The [Khronos buffer-update documentation](https://registry.khronos.org/OpenGL-Refpages/gl4/html/glBufferSubData.xhtml)
describes potential pipeline stalls when updating a referenced buffer.
The existing [memory barriers](https://wikis.khronos.org/opengl/GLAPI/glMemoryBarrier)
remain between shader work and subsequent buffer access.
These contracts are not a claim that the host structural tests prove driver behavior.

## Completed VM comparison

[Public numeric evidence](SINGLE_WAIT_ABBA_RESULTS.json) contains all eight ABBA
cohorts and source/binary pins. Both prepared frames passed 49,766,400 stage-value
comparisons per cohort. Kodi remained active; all 512 MiB/no-swap resource guards
passed without limit/OOM events. Public data contains no private input hashes,
pixels or real metadata coefficients.

| Cohort | Three warm whole-pass times (ms) |
|---|---|
| 2296-1-baseline | 587.258, 483.088, 427.267 |
| 2296-2-single | 714.269, 628.779, 450.437 |
| 2296-3-single | 571.053, 575.086, 649.321 |
| 2296-4-baseline | 623.109, 594.143, 655.496 |
| 1406-1-baseline | 580.428, 564.112, 412.563 |
| 1406-2-single | 270.256, 595.604, 589.413 |
| 1406-3-single | 529.601, 528.132, 675.705 |
| 1406-4-baseline | 544.786, 623.687, 545.994 |

Six-pass pooled medians:
- Frame 2296: two waits 590.700 ms; single wait 601.932 ms.
- Frame 1406: two waits 555.053 ms; single wait 559.507 ms.

No performance gain is established; the experiment is not adopted in playback.
The few-percent median differences, broad overlapping ranges and uncontrolled
GPU clocks/scheduling do not establish a general regression either.
Neither path is real-time here. Exactness is agreement with our unchanged C
reference, not licensed-player agreement or Dolby conformance.

## Build and host guards

Use the reduced-output runner's dependencies, original shader and strict build
flags, replacing its main C source with
`engine/experimental/native_gpu_scaled_frame_single_wait_probe.c`.
CLI arguments and CPU-only `--validate` mode are unchanged.
Seventeen normal and seventeen UBSan host tests passed. Inherited malformed-input,
width, geometry, complete-gate and suffix guards remain; the new structural test
checks one finite wait after ordered upload/dispatch/barrier and before readback.
It does not execute GPU work.

Next: a bounded resident-input experiment, reporting per-new-frame preparation
and completed upload separately from resident execution. Do not hide those costs
or present repeated execution of one prepared frame as movie playback.
