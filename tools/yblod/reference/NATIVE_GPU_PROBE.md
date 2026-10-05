# Isolated integer GPU arithmetic probe

This is a small desktop-OpenGL compute test, not a Kodi backend. It compares
every output of a public integer shader with the native C reference, using
explicit synthetic fixtures. Python only creates fixtures, runs tests and
collects reports; it does not perform the GPU arithmetic.

The first shader supports polynomial base mapping, enhancement correction and
final composition. **MMR is explicitly unsupported in this version**, including
MMR configurations that pass the separate signed-64-bit width guard. There is
no automatic CPU fallback or partial substitution during a GPU test.

The first reviewed LibreELEC VM run completed successfully: **all 6,228 GPU
stage comparisons matched exactly**, covering 1,557 sample positions across
21 polynomial fixtures. All 27 CPU fixture checks finished first; six valid
MMR configurations were then explicitly rejected without GPU dispatch.

The public report is
[native-gpu-probe-libreelec-20261005a.json](results/native-gpu-probe-libreelec-20261005a.json).
It pins every source, fixture, shader and binary, preserves individual command
logs and results, and records zero mismatches in all four stages. The native
CPU results were independently checked against Python before GPU execution.

The run used the previously verified Intel render node on the LibreELEC VM,
with a 512 MiB memory ceiling and job swap disabled. Peak charged memory was
61,149,184 bytes (58.32 MiB); limit-pressure, OOM/OOM-kill and swap counters
were zero. Parent peak RSS was 23,668 KiB and maximum child RSS 100,516 KiB;
these are different accounting measures, not contradictory GPU-memory totals.
Kodi remained active afterwards. The 0.731-second aggregate diagnostic time
includes setup and verification and is **not** GPU throughput or playback cost.

Executed artifact pins:

- Main C source: `4ea8e1753d9b32b12301fc44c626a4810dc129784bee2fc3caa24933072775b3`
- Shader: `adab2f868ac0dee19bb248c6950724abd6238c0315a03162b1e08d883f21ba83`
- SDK executable: `3c0f397f22e63daa22d2a96679ec46dbb3ca3c888561ab41ead46820d4feaee6`

This establishes exactness for this synthetic polynomial/NLQ/composition corpus
on this driver, not full metadata coverage, MMR execution, raw-Y416 processing,
Kodi integration, real-film accuracy or licensed Dolby conformance.

## Input contract and rejected cases

The native fixture loader accepts 1..4,096 sample triplets and optional integer
EL codes. It validates all metadata and every input before any EGL/device call.
It shares the native CPU metadata envelope, with these explicit v1 restrictions:

- Mapping is polynomial only; all configured MMR segments reject GPU dispatch.
- BL and EL may independently use 8 or 10 bits. Each sample and the NLQ offset
  are checked against their own layer's depth.
- Mapping and NLQ use the same global coefficient denominator, matching the
  existing chunk/frame contract. The encoder rejects different denominators;
  it never rewrites an NLQ denominator silently.
- Output depth is explicitly 10 or 12. Disabled enhancement requires both NLQ
  configuration and EL samples to be absent; its serialized EL fields are zero.
- Fractional inputs, booleans and out-of-range values are rejected by the fixture
  encoder, not truncated into native codes. This is not a raw-Y416 import path.

`native_gpu_guard` reports width eligibility separately from algorithm support.
This leaves valid-but-unsupported metadata distinct from malformed metadata.
No licensed-player matching, fitted offsets or new colour-clipping policy is
part of the test.

## Arithmetic

The shader keeps right-owned internal pivot intervals and clamps the driven
component to its own outer pivots. Polynomial accumulation uses signed 64-bit
integers. With supported depths and denominators, each term is at most 2^58 in
magnitude and the three-term sum is below 2^60, safely within that type.

Enhancement correction retains its independently declared EL depth, signed
half-step threshold, exactly neutral zero and metadata accumulator limit.
The limit is applied **before** signed flooring. The flooring helper shifts
only nonnegative operands and preserves negative mathematical floor, including
shift zero. NLQ intermediate bounds fit well inside signed 64-bit storage.

The shader then adds mapped base and signed correction, retains the unclipped
sum, adds the single output-rounding bias, floors once and finally bounds the
10/12-bit reconstructed output. The four reported comparison stages are mapped
base, signed correction, unrounded sum and reconstructed output.

## Explicit buffer layout

No native C structure is copied to an assumed GLSL structure layout. Host code
packs scalar arrays explicitly and checks scalar widths. The probe currently
requires a little-endian host for its raw GPU upload convention.

| Binding | GLSL declaration | Host layout |
|---|---|---|
| 0 | `int64_t m[]` | 93 signed 64-bit words, 8-byte stride |
| 1 | `uvec4 samples[]` | Y, Cb, Cr, EL as four unsigned 32-bit words, 16-byte stride |
| 2 | `ivec4 results[]` | Mapped, residual, sum, reconstructed as four signed 32-bit words, 16-byte stride |

Metadata is 744 bytes. Each sample/output buffer is at most 65,536 bytes. Output
words start at `INT32_MIN`, which is impossible for all four expected stages:
an unwritten output cannot accidentally pass an all-zero fixture.

Metadata words 0..10 carry count, component, enabled flag, output depth, BL depth,
shared denominator, EL depth, offset, slope, threshold and maximum. Word 11 is
pivot count; words 12..28 are the 17 pivot slots. Each of the 16 segment slots
then carries order plus three polynomial coefficients, starting at word 29.
Unused slots are zero and validated in the native fixture metadata.

The separate input-file format is explicitly little-endian, not a memory dump:
8-byte `YBGPU01\0` magic, eight 32-bit header fields, three 64-bit NLQ fields,
three fixed component mappings, then four 32-bit words per sample. Signed
coefficients are decoded without implementation-defined unsigned-to-signed
overflow. Exact length, EOF, regular-file size and before/after file identity,
timestamps and sizes are checked. These detect ordinary changes, not malicious
concurrent filesystem attacks or cryptographic source authentication.

## GPU isolation and completion

The tool repeats the capability diagnostic's explicit render-node association:
character-device identity, unique nonsoftware EGLDevice, device-platform display
and display-to-device verification. It creates a private surfaceless desktop
OpenGL 4.3-or-newer core context and requires advertised
`GL_ARB_gpu_shader_int64`. Software renderers are rejected.

Actual compute and storage-buffer limits are queried before allocating the
three private buffers. The linked shader must report work-group dimensions
exactly `[64,1,1]`. One invocation owns one output position, and excess
invocations immediately return. Polynomial and pivot loops are bounded by
previously validated metadata.

One compute dispatch is followed by the required storage/buffer barrier, a
fence and a client wait with a five-second timeout. There is no unbounded
`glFinish` loop. Successful completion is required before bounded readback.
All four result arrays are compared against the C reference. Shader/link logs,
failure operation, observed GL/EGL error, mismatch counts, device association
and cleanup status are recorded.

The shader file is a trusted, reviewed diagnostic artifact, not an arbitrary
untrusted shader sandbox. The aggregate runner must pin that exact file before
and after execution; a compatible work-group declaration alone cannot prove an
arbitrary replacement shader is safe or implements this arithmetic.

Owned buffers, fence, program, shader, context, display and descriptor are
released. No window, presentation surface, draw, swap, KMS, Kodi or display-mode
operation is part of the tool. Context/resource creation and compute execution
are real GPU work, so live runs require their separate reviewed authorization.

## Build and host-only verification

With a compatible SDK and existing EGL/GL development headers:

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
  native_gpu_probe.c native_gpu_probe_fixture.c \
  native_composer.c native_gpu_guard.c -lEGL -o native_gpu_probe
```

The initial SDK artifact was compiled with LibreELEC GCC 16.2.0 in a networkless
container with one CPU, 512 MiB memory and no container swap. It requires no
new runtime library beyond existing EGL/libc; required glibc symbols are no
newer than 2.34.

A host-only build contains no EGL dependency or GPU execution path:

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
  -DYB_GPU_PROBE_HOST_ONLY native_gpu_probe.c native_gpu_probe_fixture.c \
  native_composer.c native_gpu_guard.c -o native_gpu_validate
python3 native_gpu_probe.py NEW-SYNTHETIC-FIXTURE-DIRECTORY
./native_gpu_validate --validate FIXTURE.bin
python3 -m unittest test_native_gpu_probe test_native_gpu_vectors
```

The reviewed aggregate runner performs all CPU checks before its GPU cases and
writes a source-pinned report into a fresh directory:

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 native_gpu_run.py ./native_gpu_probe ./native_gpu_probe.comp \
  NEW-GPU-RESULTS --device /dev/dri/renderD128
```

Validation exits 0 for the GPU-eligible subset, 3 for valid but unsupported
metadata, and 2 for invalid fixtures. JSON always identifies whether GPU work
was attempted. The host-only test path returns all four CPU stages for the
independent Python oracle to check.

The initial independent corpus has 27 fixtures: 21 polynomial candidates and
six deliberately unsupported MMR cases. Tests include independent BL/EL depths,
right-owned pivots, negative floor, limiting before floor, coefficient extremes,
disabled enhancement, malformed/truncated/extra data and width boundaries.
Host tests and undefined-behaviour-sanitized validation passed before any live
GPU authorization. This is not a throughput, full-frame, raw-Y416, display
accuracy or Dolby-conformance claim.

## Reproduce the bounded aggregate diagnostic

`native_gpu_run.py` completes every independent CPU gate before any GPU context
is opened. It pins the reviewed sources, shader, executable and serialized
fixtures before/after every invocation, rejects unsupported cases explicitly,
and stops on the first mismatch, error, changed file or subprocess timeout.
Reports require exact numeric types, matching width/algorithm declarations,
successful completion fences, verified device association and cleanup.
The output directory must be new; fixtures and command logs remain available.

On a compatible Linux machine, using a target-compatible native executable:

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 native_gpu_run.py /path/to/native_gpu_probe \
  ./native_gpu_probe.comp NEW-RUN-DIRECTORY --device /dev/dri/renderD128
python3 -m unittest test_native_gpu_run
```

The initial aggregate uses 27 validation subprocesses and 21 GPU subprocesses.
Every actual calculation runs in native C or the shader; Python supplies the
independent synthetic oracle and orchestration. The scope limit is externally
enforced by `systemd-run`, not by the Python process. Before/after cgroup
snapshots retain detailed memory counters for future diagnosis; RSS and charged
memory measurements do not bound all GPU allocations. Source pins detect
ordinary mutations, not adversarial authentication of the executable or driver.
