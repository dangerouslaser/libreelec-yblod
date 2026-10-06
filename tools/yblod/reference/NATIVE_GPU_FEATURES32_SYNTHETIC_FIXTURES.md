# Public synthetic composer qualification fixtures

`native_gpu_features32_fixture.c` generates deterministic 64×64 whole-code
frames and same-build native instruction blobs for the existing
`native_gpu_composer_image_probe.c`. No media, decoder capture, display
calibration or metadata fitting is used. The instruction blob is the existing
9,216-byte native ABI artifact; it is not a portable interchange format.

The initial six cases combine MMR orders 1, 2 and 3 with output depths 10 and
12. All inputs remain 10-bit. Every component has six pivots
`[0,1,100,300,700,1023]`, signed coefficients, and discontinuous segment
coefficients. Luma uses quadratic polynomial mapping; both chroma components
use the selected MMR order. Order 2 uses denominator 32; the others use 23.
Input patterns include endpoints and values adjacent to interior pivots.
They are deliberately varied, not an exhaustive Cartesian sample sweep.

The default NLQ configuration tests exact-offset zero and saturated positive
and negative corrections. Its large slope saturates every nonzero integer
distance. It does **not** establish unsaturated-transition or general deadzone
coverage. An optional final argument `small` generates a separate small-slope
variant with a smaller slope; that variant needs its own CPU/GPU evidence
and must not inherit a default-case pass. Observed transition coverage is
not inferred from those settings alone.

## CPU and paired GPU gates

All six default cases and six small-slope cases compiled/generated with strict SDK warnings and passed
the existing native CPU full-frame oracle in validation-only mode, checking
24,576 stage values per case (294,912 total) before GPU execution. Subsequently,
all twelve cases passed both the canonical and features32 shaders using the
same unchanged backend runner: 24 bounded GPU jobs. Each compared every one of
6,144 reconstructed output codes across all three planes to the native CPU
oracle. Total paired coverage was 147,456 GPU codes and 589,824 CPU stage
values. Warm timing passes checked the error flag only and are not additional
full-output oracle coverage.

The GPU JSON preserves all three wall and CPU timing samples for both sides
of every case, including slower candidate samples. These 64×64 timings are
host submission/completion overhead and jitter, not a 4K performance
qualification. Before/after resource limits, memory events, swap, CPU
throttling, available clock readings, binary/shader/input/runtime hashes and
Kodi process identity were captured. Input files matched their generation
source hashes before execution. Each job was limited to 512 MiB/no additional
swap/one CPU/60 seconds. No canonical shader or playback route was changed.

Small-slope coefficient settings do not by themselves prove observed residual
transition coverage: no per-stage transition histogram was measured. Passing
these fixtures is scoped exact-output evidence, not exhaustive correctness or
whole-pipeline colour/display accuracy. Features32 remains an unadopted
candidate pending separate reviewed real-playback performance evidence.

## Reproduction

Compile the generator with `native_gpu_guard.c` and `native_composer.c`, the
engine include/experimental header paths and strict C11 warnings. Pass a new
empty directory, MMR order (`1`, `2`, `3`) and output depth (`10`, `12`), with
optional `small`. The generator refuses to overwrite existing files; a failed
write may leave partial files, so retry in another empty directory.

The six generated names are `instructions.bin`, `bl_Y.u16le`, `bl_Cb.u16le`,
`bl_Cr.u16le`, `mmr_luma.u16le` and `scaled1.p010`. Use the existing runner CLI
with `--validate` in place of the render node first, then run the same backend
and fixtures once with the canonical shader and once with the candidate shader
under an authorized exclusive GPU scope. Compare every reconstructed code to
the CPU oracle. Wall times for these tiny cases are correctness-gate overhead,
not a useful real-playback performance estimate. Keep the canonical engine
unchanged until paired evidence is reviewed.
