# Full-frame integer GPU baseline

This isolated C diagnostic extends the sampled GPU arithmetic test to complete
prepared 3840×2160 frames. It does not change Kodi, decode a movie, resample
an enhancement layer, or tune its results to a licensed player.

Both tested frames passed: all **49,766,400 intermediate stage values per frame**
matched the unchanged C reference exactly, across 191 bounded dispatches.
The four stages are mapped base, signed enhancement correction, signed
unrounded sum, and reconstructed output.

The important performance result is negative: the current diagnostic GPU
transport is slower than our optimized C checkpoint. Median warm elapsed time
was **798.60 ms** for the Intel-scaled input and **754.08 ms** for the
software-linear-scaled input. The historical C checkpoint was approximately
212 ms, but it was not directly paired with these GPU runs. These are not
playback frame rates.

The source-pinned aggregate checkpoint is
[results/native-gpu-scaled-frame-vm-20261005a.json](results/native-gpu-scaled-frame-vm-20261005a.json).
It contains timings, counts, source/binary hashes and resource outcomes, but
no picture samples, metadata coefficients, private paths or private input hashes.
Tests audit that saved evidence; they do not rerun the VM.

## Scope and safety

The new runner is `engine/experimental/native_gpu_scaled_frame_probe.c`.
The established shader is unchanged. Supporting GPU guard and fixture-helper
sources are available beside it; the legacy sampled diagnostics are unchanged.
This experimental target is outside the default engine build.

Inputs are an explicit same-build 9,216-byte instruction structure, three
prepared whole-code base planes, a prepared chroma luma guide, and a coherent
tightly packed P010 scaled surface. This checkpoint deliberately supports only
whole 10-bit input codes, enabled enhancement, polynomial luma mapping and
10/12-bit output. Fractional P010 values are rejected, not rounded. It does not
settle enhancement scaling or fractional transport policy.

All six files must be distinct regular files of exactly the expected size,
with stable identities during loading and no final-path symlinks. File data is
retained as an immutable in-memory snapshot. The external private scope wrapper
pins inputs, executable, shader and runtime before and after execution.
Saved frame/extraction association belongs to that preparation workflow: this
runner does not itself parse an RPU or authenticate a movie.

Invalid metadata and input are rejected before width-ineligible valid metadata
is reported unsupported. The signed-64 GPU guard checks every used MMR segment;
unsupported metadata never silently falls back and claims GPU success.
The complete unchanged C and established cached C stages agree before any GPU
access. A subsequent untimed GPU pass compares every stage of every sample with
a fresh unchanged C frame, including final partial chunks and complete counts.

The persistent EGL context is bound to the explicitly requested hardware render
node. Software rendering, missing integer-64 capability, inadequate compute or
buffer limits, unexpected linked work-group size, allocation-size disagreement,
GL/EGL failures, fence timeout and failed cleanup all prevent success.
One reusable input/output buffer pair holds at most 65,536 samples. Output
sentinels are reset before every dispatch.

## What the timings mean

Cold setup includes device/context initialization, shader compile/link and
bounded scratch/buffer allocation. "Cold" here means a new process/context,
not a deliberately cold Mesa shader cache; driver cache state was uncontrolled.
Teardown is reported separately.

After complete exactness verification, one pass warms the persistent context
and three complete passes are timed. Warm totals include enhancement extraction,
input packing, per-component metadata preparation, metadata/input/output-sentinel
uploads, dispatch, barriers, bounded fence waits, and four-stage output readback.
They exclude file I/O, input/stage scratch allocation and CPU oracle comparisons.

Timed passes check only their final chunk against saved exact output, outside
the timer. They are not three new complete-frame comparisons. Complete GPU
correctness was required before timing.

Process CPU timing covers this process and its driver calls, not total GPU
execution or every external driver thread. Subtracting CPU time from elapsed
time does not isolate shader computation. The baseline cannot yet attribute
its cost to arithmetic, transfers, synchronization or driver overhead.

The separately measured [phase-profile companion](NATIVE_GPU_SCALED_FRAME_PROFILE.md)
separates cumulative preparation, uploads, dispatch/wait and readback.
Host-observed dispatch/wait remains a combined category, not a GPU-kernel timer.
Larger chunks, queued buffer sets and
resident-input/final-only-output variants are later transport experiments,
each requiring independently reported correctness and timing scope.

## Resources and integration

The two jobs enforced 512 MiB and zero job swap. Recorded charged peaks were
109,195,264 and 102,432,768 bytes, respectively. No memory-limit, OOM or OOM-kill
events occurred. Charged scope memory is not total system/GPU allocation.
Kodi remained active before and after both jobs. No TV or playback settings
were changed.

This is desktop OpenGL compute with explicit integer-64 arithmetic. Kodi's
current GLES renderer and decoder/surface interoperation remain separate
integration work. Exact agreement with our reference is not proof of licensed
Dolby output, display colour accuracy or Dolby conformance.

## Build and run

Build the experimental runner and external arithmetic units without LTO:

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror -fno-lto \
  -Iengine/include -Iengine/experimental \
  engine/experimental/native_gpu_scaled_frame_probe.c \
  engine/experimental/native_gpu_guard.c \
  engine/experimental/native_gpu_probe_fixture.c \
  engine/experimental/native_mmr_composer.c \
  engine/experimental/native_scaled_surface.c \
  engine/experimental/native_decoder_frame_bridge.c \
  engine/experimental/native_integration_probe.c \
  engine/experimental/native_sampling_probe.c \
  engine/src/native_composer.c -lEGL -o native_gpu_scaled_frame_probe
```

The CLI is:

```text
native_gpu_scaled_frame_probe NODE SHADER WIDTH HEIGHT INSTRUCTIONS BL-Y BL-Cb BL-Cr GUIDE P010
```

Use a private freshly created output location and the pinned external scope
wrapper; do not publish raw output or input files. A CPU-only build adds
`-DYB_GPU_PROBE_HOST_ONLY` and omits EGL/GL libraries. Replacing NODE with
`--validate` enables full CPU validation and ignores SHADER without opening
a GPU. The native executable itself does not enforce its cgroup: the caller
must enforce 512 MiB/zero swap and verify resource outcomes.

```sh
cd tools/yblod/reference
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  test_native_gpu_scaled_frame_probe test_native_gpu_scaled_frame_results
```
