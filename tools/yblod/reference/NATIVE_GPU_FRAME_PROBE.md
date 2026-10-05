# Private prepared-frame GPU arithmetic check

This diagnostic checks selected real prepared samples using the already-tested
integer GPU shader. It does not decode a film, change Kodi, resample a layer,
choose a fractional enhancement policy or compare against a licensed player.

The sampled real-frame GPU check passed: **all 49,152 stage values matched
exactly**, covering 4,096 selected positions in each of Y, Cb and Cr from
prepared frame 2296. Each component agreed across all four arithmetic stages.
All three independent Python/native C/saved full-CPU-stage gates finished
before GPU execution.

The sanitized VM result is
[native-gpu-frame-2296-libreelec-20261005a.json](results/native-gpu-frame-2296-libreelec-20261005a.json).
The executable and shader are unchanged from the tested v2 synthetic corpus.
The executable hash is
`3b620fa0112736879bbadd5709876408566deb83b4bf4d11f960f629f0f81019`.
Peak charged scope memory was 51,187,712 bytes (48.82 MiB), with a 512 MiB limit,
zero job swap and zero memory-limit/OOM/OOM-kill events. Kodi remained active
afterwards; no TV, display mode or playback setting was changed. Charged scope
memory is not total system/GPU memory: input pages can already be cached and
charged outside the test scope. This was not a throughput measurement.

The preceding CPU-only Ollie run is
[native-gpu-frame-2296-cpu-20261005b.json](results/native-gpu-frame-2296-cpu-20261005b.json).
It used a host-only executable with no EGL/GPU execution path. Peak charged
memory was 214,802,432 bytes (204.85 MiB); swap, memory-limit and OOM/OOM-kill
counters were zero. Its status is `validated`, and `gpu_attempted` is false.
The native validator binary hash is
`1e4b2ba3a4948f7eb44e2879a6b61f2818985c4c32683cb4f9669a307f94e988`.
Both summaries pin the executed source, shader and verified input artifacts.

The first minimal VM deployment stopped at a missing Python helper import,
before any input processing or GPU work. The source inventory was corrected,
an isolated-import regression test added, and all CPU gates rerun before the
successful VM attempt. No shader or arithmetic changed for that correction.

## What it checks

The inputs are an explicit prepared `frame.json`, its completed full CPU
composition directory, and the matching extraction directory. The existing
source-association helper verifies saved extraction/RPU hashes, normalized
metadata, frame identity and geometry. It does not freshly decode a raw RPU
CRC or rehash/decode the complete film. These checks establish the saved
association, not authenticity of a deliberately forged self-consistent bundle.

Every consumed prepared plane and all twelve CPU stage files are read and
hashed in bounded chunks. Exact sizes, native-code bounds, regular-file status
and ordinary file/path changes are checked. Full hashes must match the CPU
report, and the complete prepared manifest must match its pinned copy. MMR
requires the explicitly prepared luma guide. Disabled enhancement stays
explicit: unused EL files are not silently consumed.

For each component, an endpoint-inclusive grid uses at most 64 columns and 64
rows. For an axis with size `s`, `n=min(64,s)` and coordinate `i` is
`floor(i*(s-1)/(n-1))`; the single-element axis uses coordinate zero. This is a
fixed arithmetic test grid, not representative image-quality sampling.

Luma inputs are `(Y,0,0)`. Each chroma input uses `(prepared guide,Cb,Cr)` from
exactly the same chroma index, plus its own prepared native enhancement code.
There is no additional phase shift, scaling, rounding or clamp before the
existing validated integer stages.

All three components must first agree across the independent Python stages,
selected bytes from the fully hashed CPU output, and the native C validator.
Only then may the GPU run. Width-guard rejection stops the diagnostic; there
is no CPU fallback disguised as GPU success. Input files and association are
checked again before GPU execution and after completion. Individual snapshots
and rehashes detect ordinary changes, not adversarial atomic-snapshot attacks.

## Privacy and outputs

Use a fresh private output directory. It is created with mode `0700` and holds
the binary fixtures, native CPU arrays, command logs and private report. These
contain selected picture samples and metadata coefficients: **do not publish
that directory or its private report**.

Only `public-summary.json` is intended for publication. It uses an explicit
allowlist of fixed hash-role labels, counts, gate results and numeric resource
counters. It contains no pixel arrays, RPU curves, frame identity, film title,
input manifest, command arguments, local paths or arbitrary exception text.
Opaque hashes still identify the tested artifacts. The public summary is
written last; a failed diagnostic is never labelled complete.

## Run

Use the pinned v2 native executable and shader, existing target libraries, and
a scope enforcing at most 512 MiB with job swap disabled. The CLI refuses to
proceed without observing those limits.
Successful completion also requires unchanged limits, zero active job swap,
and no new memory-limit, OOM or OOM-kill events during the run.

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 native_gpu_frame_probe.py ./native_gpu_probe ./native_gpu_probe.comp \
  PRIVATE-PREPARED/frame.json PRIVATE-CPU-RESULT PRIVATE-EXTRACTION \
  NEW-PRIVATE-OUTPUT --device /dev/dri/renderD128
```

Add `--validate-only` to run the three CPU gates without creating any GPU
context. A successful CPU-only summary says `validated`, not `complete` or
GPU-tested. The test suite deliberately uses that mode with a host-only C
executable and tiny synthetic inputs; no GPU is touched:

```sh
python3 -m unittest test_native_gpu_frame_probe
```

The public API's `require_memory_cap=False` exists for these small host tests;
the CLI has no bypass switch. The GPU dispatch itself retains the v2 probe's
4,096-sample bound, verified render-node association, finite fence timeout,
complete four-stage comparison and cleanup checks. Python selects samples and
checks results; actual GPU arithmetic remains in the native shader.

This exact result establishes only these sampled prepared whole-code
calculations. It does not establish full-frame GPU correctness, real-time
performance, colour-output accuracy, raw-Y416 handling or Dolby conformance.
