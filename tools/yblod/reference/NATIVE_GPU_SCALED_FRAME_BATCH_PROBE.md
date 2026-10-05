# Isolated larger-batch GPU experiment

`engine/experimental/native_gpu_scaled_frame_batch_probe.c` keeps the original
full-frame probe and shader unchanged. This companion increases the maximum
GPU submission from 65,536 to 262,144 samples, while retaining the C oracle's
65,536-sample call limit. It is not Kodi integration or a new arithmetic policy.

The purpose is to measure whether fewer serialized upload/dispatch/wait/readback
cycles improve the complete diagnostic path. It does not assume that waits,
shader arithmetic or memory traffic are the sole cause of the earlier timing.
The shader's count and buffer capacity are explicitly set per batch, with
excess invocations returning as before. CPU validation, device association,
integer-width rejection, finite fences and complete cleanup remain required.

For each GPU batch, the untimed oracle pass reconstructs and compares every
position in bounded CPU subchunks. Thus `gpu_verified_dispatches` counts GPU
batches, while `gpu_oracle_dispatches` counts the smaller C comparisons.
`gpu_verified_stage_values` still counts all four stages across the full frame.
No unsupported-wide metadata is silently converted into a GPU success.

## Tail checks

The last GPU batch can contain several CPU subchunks. The saved golden array
contains only the final CPU subchunk, so the outside-timer observability check
must compare it with the corresponding **suffix**, not the start of the GPU
readback. `golden_suffix_samples` reports that final CPU count. The complete
untimed frame gate remains the correctness claim; timed checks are explicitly
labelled `final-CPU-subchunk-suffix-only`.

Synthetic host tests cover a 512x512 frame whose luma exactly fills one GPU
batch, a 514x512 frame with a partial luma GPU tail and partial chroma CPU tails,
and malformed input after the batch boundary. They inherit the full input,
alias, width and malformed-before-unsupported guards. Source audit checks
protect the distinct CPU/GPU bounds and suffix comparison. Host-only and UBSan
runs execute no GPU work and cannot establish device correctness or speed.

Build with the original probe's sources and flags, replacing only its main C
file with `native_gpu_scaled_frame_batch_probe.c`. CLI arguments are unchanged.
`--validate` and `YB_GPU_PROBE_HOST_ONLY` remain CPU-only and distinguish planned
batch counts from actual GPU work. A hardware result requires a separately
completed source-pinned execution and full-frame comparison.

## Completed two-frame checkpoint

The [source-pinned aggregate result](results/native-gpu-scaled-frame-batch-vm-20261005b.json)
records four completed cohorts: the unchanged original probe and this larger
batch probe, each tested on two real prepared frames. Every complete-frame
four-stage comparison passed. These were **adjacent sequential cohorts**, not
an interleaved paired benchmark; each contains only three warm timed passes.
Each larger-batch run checked 49,766,400 values through 48 GPU batches and
191 bounded CPU oracle subchunks.

| Prepared frame | Original median, ms | Larger-batch median, ms |
|---|---|---|
| 2296 | 792.0 | 761.4 |
| 1406 | 764.2 | 651.8 |

These observations do not establish a sustained speedup: run variability and
cohort ordering remain possible influences. Larger batches are still much
slower than the separately measured approximately 212 ms optimized C path;
that historical comparison is not a new paired CPU/GPU benchmark.

Maximum charged memory across the larger-batch runs was 121,196,544 bytes
(115.58 MiB), below the enforced 512 MiB ceiling. Job swap and pressure/OOM
events remained zero. This is not a bound on all GPU/system memory. Kodi's
default playback path is unchanged.

The next useful diagnostics separate resident input and final-output-only GPU
work from the host staging and complete four-stage readback retained here.
They must be labelled as different workloads and preserve the complete
untimed correctness gate. These measurements do not justify Kodi integration
or a real-time playback claim yet.

The GPU timing includes extraction, packing, sentinel initialization, buffer
updates, dispatch, barrier, wait and four-stage readback. Cold setup and teardown
remain separate. It is neither isolated kernel timing nor production playback
throughput. Fractional Y416 precision, surface sharing and GL/GLES integration
remain separate gates.
