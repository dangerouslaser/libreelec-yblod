# Synthetic texture-sampling observation

This small standalone diagnostic records what an isolated desktop OpenGL
texture sampler and float enhancement expression actually produce. It is not
Kodi playback, a VAAPI import test, a replacement reconstruction policy or a
test of licensed Dolby rules for fractional enhancement values.

## Measured result

The first reviewed LibreELEC VM run passed its hard controls. It used one
dispatch for all 112 synthetic queries on Mesa Intel Iris Xe (TGL GT2), desktop
OpenGL 4.6 / Mesa 26.2.4. The source-pinned public report is
[native-texture-probe-libreelec-20261005a.json](results/native-texture-probe-libreelec-20261005a.json).

All observed texture values and intermediate values through the neutral guard
matched the declared sequential binary32 model bit for bit. The final
correction had small differences, which the diagnostic records rather than
silently treating as exact:

| Stage | Values compared | Different bit patterns | Largest difference |
|---|---:|---:|---:|
| Point-fetch UNORM | 448 | 0 | 0 |
| Filtered UNORM | 448 | 0 | 0 |
| Scaled EL | 448 | 0 | 0 |
| Centered EL | 448 | 0 | 0 |
| Guard magnitude | 448 | 0 | 0 |
| Guarded EL | 448 | 0 | 0 |
| Pre-colour correction | 448 | 56 | 4 ULP; absolute 3.725290298461914e−9 |

The counts include the fourth diagnostic lane; its non-colour correction
values are deliberately zero. Guard decisions had no model differences.
The ideal-rational sampling comparison reached at most 0.00098419189453125
raw-word-equivalent error; post-scale error reached at most
0.00003096461296081543 native-code equivalents. These are observations for
this small fixture, not universal precision guarantees.

For an explicit point-sampled Y example, raw neutral word 32768 triggered the
guard and returned zero correction. Words 32752 and 32784 (native equivalents
511.75 and 512.25) did not trigger it, and produced approximately +4.0000038
and −4.0000038 in 16-bit correction units. This demonstrates the inspected
float formula's behavior on these fractions, not whether licensed Dolby would
choose that behavior. The final bit differences do not, by themselves,
identify a particular fused instruction or compiler transformation.

All integer-storage, normalization-endpoint, finite-value, zero-lane and guard
controls passed. Render-node association, format capabilities, fence, GL/EGL
state and cleanup passed. Peak charged memory was 40,914,944 bytes (39.02 MiB)
under 512 MiB with zero swap/limit/OOM events. Kodi remained active afterwards.
The aggregate 0.091-second setup/check duration is not throughput or playback
cost. No second GPU cohort was run.

The executed SDK binary SHA256 is
`7e5cecf3fbafa2ba84b1b1167fe87038877b34ec5e203813ea5a31c9c4ba3996`.
It was built with GCC 16.2.0, strict warnings, no fast-math and FP contraction
disabled for host C, in a 512 MiB/no-swap container. The report pins all four
executed implementation files. Complete synthetic sources, binary, logs and
results were archived on Ollie with hashes, sizes and permissions checked.

## Fixed input and outputs

Only a fixed public synthetic fixture is accepted: an 8×2 texture with four
unsigned 16-bit words per pixel, interpreted as U/Y/V/A. A normalized RGBA16
texture and an integer RGBA16UI control receive the same bytes. There are 112
declared queries, each with explicit logical quarter-texel coordinates and
nearest or linear filtering. Clamp-to-edge is explicit. Inputs include whole
codes, quarter codes, individual low-word differences, neutral values,
component/alpha differences and borders.

The integer-control fetch uses the clamped floor of the declared logical
coordinate. It is deliberately distinct from nearest filtered sampling, which
uses the half-texel texture convention: a logical coordinate of 4.5 selects
index 5 for nearest sampling, while the control fetch still selects index 4.
Linear sampling at that coordinate blends indices 4 and 5.

Each query returns 36 uint32 words. No float-valued framebuffer is involved:
`floatBitsToUint` writes observed float results directly to a storage buffer.

| Word positions | Meaning |
|---|---|
| 0–3 | Integer-control U/Y/V/A words |
| 4–7 | Point-fetch UNORM values, as float bits |
| 8–11 | Declared nearest/linear sampled UNORM values |
| 12–15 | Sample multiplied by the uploaded representation scale |
| 16–19 | Centered enhancement signal; fourth lane zero |
| 20–23 | Neutral-noise guard magnitude; fourth lane zero |
| 24–27 | Guarded signal; fourth lane zero |
| 28–31 | Signed pre-colour correction; fourth lane zero |
| 32–35 | Three guard decisions and a zero fourth lane |

The report preserves the actual parameter float bits. The synthetic fixture
uses native depth 10, denominator 23, offset 512, slope 2048 and threshold zero,
converted with the inspected source's arithmetic order. Its scale is the
float result of `1/64` multiplied by the double ratio `65535/1023`; its offset
uses the already rounded float `1/1023` multiplied by 512. The uploaded slope
and threshold are 0.249755859375 and −0.0001220703125.

The reproduced subset is the normalized float neutral guard, sign, slope and
threshold expression from the pinned libplacebo
`src/shaders/colorspace.c` lines 106–149, SHA256
`5961adebdc5f4768eb6cf28560f9cb1143c65d3cfbe6be089097347dc232ebcf`.
See [the source audit](EL_SHADER_SAMPLING_AUDIT.md) and
[the earlier arithmetic audit](NLQ_SHADER_AUDIT.md). It is explicitly a test of
that source-style float formula on synthetic fractional values, not a normative
extension of the standalone integer NLQ reference. It does not model the
integer reference's maximum-residual cap, mapped-BL addition, output rounding,
colour matrices or output transport. No maximum metadata parameter is supplied
to this isolated shader.

## Interpretation and hard gates

The host observer compares against both exact rational sampling and a declared
sequential binary32 calculation. It records bit differences, ULP distances,
absolute errors and guard-branch differences; those are observations, not a
universal one-ULP acceptance rule. Signed zero has zero numerical ULP distance
but different bits remain counted separately.

The sequential model is not a GPU emulator. In particular,
`float(float(word/65535)*float(65535/65472))` need not match
`float(word/65472)`. Texture interpolation may have different finite precision,
and driver compilation may contract operations differently. Near the neutral
guard, branch changes are reported explicitly rather than hidden by a broad
relative-error tolerance.

Hard checks are exact integer-control words and component order; exact 0/1
normalization endpoints; finite and fully written observations; valid guard
flags; zero non-colour arithmetic lanes; zero residual for zero guarded input;
and internal guard-decision consistency with the recorded centered/noise
values. A negative-zero residual is allowed. Format capabilities, device
association, successful fence completion, GL/EGL errors and cleanup must also
pass. A passed hard gate does not imply float results match either host model.

## Isolation, build and use

The C tool requires a uniquely associated, nonsoftware EGL device for the
explicit render node and a private surfaceless desktop OpenGL ≥4.3 context.
It checks RGBA16/RGBA16UI support and full linear-filter support, then compute,
texture and storage-buffer limits before allocation. No integer-64 shader
extension is required. Three separate sampler objects select nearest, linear
and integer-control behavior. There is one 2×64-invocation dispatch, a storage
barrier and a fence with a five-second client wait. A NaN sentinel detects
unwritten float outputs. Owned objects/context/display/descriptors are cleaned
up and cleanup errors prevent successful status.
The `GL_FILTER` query's support enums are defined by
[ARB_internalformat_query2](https://registry.khronos.org/OpenGL/extensions/ARB/ARB_internalformat_query2.txt);
this diagnostic conservatively requires `GL_FULL_SUPPORT`, not caveated support.

The reviewed shader is trusted diagnostic code, not an arbitrary-shader
sandbox. The Python wrapper pins the binary and all four implementation files
before and after execution, runs native fixture validation first, enforces a
512 MiB/zero-swap scope and rejects newly observed memory pressure/OOM events.
It writes a completed report only after all gates pass. All inputs and report
data are synthetic; there are no private film/RPU inputs.

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
  -fno-fast-math -ffp-contract=off native_texture_probe.c -lEGL -lm \
  -o native_texture_probe
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 native_texture_probe.py ./native_texture_probe \
  ./native_texture_probe.comp NEW-RESULTS --device /dev/dri/renderD128
```

Host-only builds exclude all EGL/GL calls and require no GPU headers/libraries:

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
  -fno-fast-math -ffp-contract=off -DYB_TEXTURE_PROBE_HOST_ONLY \
  native_texture_probe.c -o native_texture_validate
./native_texture_validate --validate
python3 -m unittest test_native_texture_probe
```

The wrapper's `--validate-only` mode stops after the fixed fixture check. Host
compiler flags govern the CPU's parameter construction, not the GPU compiler's
floating-point transformations. The report's `observed` status means the
diagnostic's hard gates passed, not that a floating-point conformance oracle
approved every bit.

Desktop GL upload/sampling is distinct from Kodi's GLES context and imported
EGLImage/VAAPI surfaces. The latter still need their own loaded-build, format,
coordinate and precision evidence. This diagnostic changes no display mode,
window, KMS state, Kodi setting or production arithmetic.
