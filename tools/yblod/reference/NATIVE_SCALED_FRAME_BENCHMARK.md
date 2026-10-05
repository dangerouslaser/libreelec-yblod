# Offline C reconstruction timing baseline

The first real-frame VM measurement took **583–601 ms per 3840×2160 frame**
for the current diagnostic C path. This is not a playback FPS measurement and
does not demonstrate real-time readiness. It establishes an honest baseline
before optimization; no arithmetic changes were made for this checkpoint.

The three measured passes were 587.463160, 600.529263 and 583.151558 ms, after
one excluded warmup. Each completed Y/Cb/Cr counts of 8,294,400 / 2,073,600 /
2,073,600 using chunks of at most 65,536 samples.

## Exactly what was measured

The monotonic timer includes exact P010-to-whole-code extraction, all four
integer outputs (mapping, residual, sum and reconstruction), and C frame
completion. It excludes input file reads, global whole-code preflight,
initialization/reset, decoding, GPU scaling, colour, packing and display output.
The engine copies real decoder instructions from an opaque same-build blob;
the benchmark accepts no JSON coefficient configuration and does not round
fractional samples. Fractional P010 anywhere in the frame rejects the job
before the timer starts.

The VM reported an Intel i5-1135G7 CPU and four online virtual CPUs. The scope
did not expose a CPU quota controller or throttling counters, so those are
reported as unavailable—not assumed unlimited or unthrottled. This sequential
diagnostic does not use all four vCPUs in parallel. Kodi remained active.

A fresh 512 MiB scope with zero allowed swap recorded a pre-exit peak snapshot
of 55,922,688 bytes (about 53.3 MiB), zero swap and zero max/OOM/OOM-kill events.
That snapshot is not the final lifetime peak. A prior wrapper attempt stopped
before C execution because the optional CPU quota file was absent; its evidence
was preserved separately and it is not counted as a successful benchmark.

## Building and running

The authoritative source belongs in `engine/experimental/`; the reference
directory retains a compatibility link. This diagnostic remains outside the
default standalone engine build.

From the repository root, with a C compiler supporting the existing engine:

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
  -fno-fast-math -ffp-contract=off -I tools/yblod/reference \
  tools/yblod/reference/native_scaled_frame_benchmark.c \
  tools/yblod/reference/native_scaled_surface.c \
  tools/yblod/reference/native_decoder_frame_bridge.c \
  tools/yblod/reference/native_integration_probe.c \
  tools/yblod/reference/native_composer.c \
  tools/yblod/reference/native_sampling_probe.c -o native_scaled_frame_benchmark
```

The CLI takes width, height, native instruction blob, prepared BL Y/Cb/Cr,
prepared quarter-resolution luma guide and tightly packed scaled P010:

```text
native_scaled_frame_benchmark width height instructions BL-Y BL-Cb BL-Cr guide P010
```

Use externally pinned input, executable, source and runtime identities, a fresh
512 MiB/no-swap scope, and pre/post memory-event checks. The same-build blob is
not a portable format. Input files must be regular, distinct files of exact
sizes; symlinks and FIFOs are rejected. BL/EL depth is fixed to native ten-bit,
enhancement is required, and luma MMR is explicitly unsupported by this test
fixture's quarter-resolution chroma arrangement. Geometry may be reduced to
2×2 for synthetic tests but may not exceed 3840×2160.

Five synthetic guard tests cover successful completion, fractional samples,
late invalid BL codes, malformed sizes/instructions, unsupported luma MMR,
symlinks/FIFOs, shared-file aliases and invalid dimensions. Their timings are
not performance results.

The public result excludes movie bytes, coefficients, input hashes, paths and
stage hashes. It does not claim equivalence to the older prepared linear
scaler or independent arithmetic correctness. The next step is profiling this
unchanged baseline to locate costs before selecting an optimization.
