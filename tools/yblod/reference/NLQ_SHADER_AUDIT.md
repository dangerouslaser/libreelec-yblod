# Enhancement-layer reconstruction: inspected shader arithmetic

2026-10-05. Read-only source audit; no playback, hardware, driver or production
code changes.

## Plain-language findings

The inspected playback shader keeps the small fractions produced by the scaler.
It does **not** first turn them back into whole 10-bit enhancement-layer values.
That distinction matters most close to the enhancement layer's neutral value.

The shader has a very small guard that removes numerical noise around neutral.
For the coefficient fixture examined here, the guard is about **one hundred and
twenty-eighth of one raw Y416 word**. It is not a half-code rounding rule and
does not resolve the larger uncertainty about fractional inputs to reconstruction.

Two other differences from our standalone integer reference are explicit in
these sources: the shader does not apply the metadata's maximum-residual bound,
and it does not immediately round the reconstructed picture to 12 bits. These
are implementation differences to test, not evidence that changing either one
would improve real playback. The inspected coefficient fixture does not reach
that residual bound over valid 10-bit input values: the largest absolute integer
accumulator is 2095104, below the limit 2097152. A missing clamp is therefore
**not a demonstrated error on this fixture**. A deliberately binding synthetic
fixture would first need a defensible metadata-legality contract.

This audit establishes what the inspected source says. It does **not** establish
that the currently loaded Kodi binary contains this exact source, which shader
the GPU compiled, or how licensed Dolby hardware handles fractional inputs.

## Source identity and reproducibility

The inspected LibreELEC reconstruction worktree was:

```text
/home/bryan/Projects/libreelec-yblod-reconstruction
HEAD c6c96ed16e411182038bf754d92844864f09fe97
```

The separate existing build-source directory on Ollie was:

```text
/home/bryan/Projects/libreelec-yblod/build.LibreELEC-Generic.x86_64-13.0-devel/build/libplacebo-e2972fdd09adacd383656738d7d280f0cd84a761
```

The tracked libplacebo package pins version
`e2972fdd09adacd383656738d7d280f0cd84a761`. The table below pins the actual
inspected, patched build files, not just that upstream version string. Paths in
the first five rows are relative to the build-source directory; the last two
are relative to the reconstruction worktree.

| Source | Relevant lines | SHA256 |
|---|---|---|
| `src/shaders/colorspace.c` | 106–149; 314; 337–369; 453–483 | `5961adebdc5f4768eb6cf28560f9cb1143c65d3cfbe6be089097347dc232ebcf` |
| `src/include/libplacebo/utils/libav_internal.h` | 924–929; 954–986; 996–1017 | `542055662c561cbccbb479a89be0ed1b6e295bbc7b2298a83d8424d053d14189` |
| `src/include/libplacebo/colorspace.h` | 150–166 | `045ae8a75caa8d1dc50dcfdf1b190817af3a07c0d381df20d86178095dab9a0d` |
| `src/colorspace.c` | 177–220; 1818–1819; 1921–1926 | `0099300821d9960dd291f2b6ac22eb5779e95326ae327c488030268e8c02f5e3` |
| `src/renderer.c` | 1593–1678 | `b4318cb4ee2199d0b7ed2202b5e950d2a9dcbb368300e9d1d5d9fa8d3f65e1f5` |
| `projects/Generic/patches/kodi/kodi-9999-yblod-01-qsv-offload.patch` | 128; 141–153 | `209e16d08cc04a15c34dbb182f8fde284004fc6aa0bc2ad58bd743caa6eb79ff` |
| `packages/addons/addon-depends/multimedia-tools-depends/libplacebo/patches/libplacebo-9910-4.patch` | 12–16 | `69c953b17a4a54b637d1dea07e56a203a14bd437b7e1b8a95bcf769766131070` |

Use `sha256sum` on these files and `nl -ba FILE` to reproduce the source
identification before relying on the line numbers. The guard is visible in the
[tracked patch](https://github.com/dangerouslaser/libreelec-yblod/blob/c6c96ed16e411182038bf754d92844864f09fe97/packages/addons/addon-depends/multimedia-tools-depends/libplacebo/patches/libplacebo-9910-4.patch#L12),
and the Y416 representation is declared in the
[tracked import patch](https://github.com/dangerouslaser/libreelec-yblod/blob/c6c96ed16e411182038bf754d92844864f09fe97/projects/Generic/patches/kodi/kodi-9999-yblod-01-qsv-offload.patch#L128).

## Raw Y416 word to shader input

The import declares 16-bit storage, 10-bit colour depth and a six-bit shift. Its
packed U/Y/V components are mapped to Cb/Y/Cr; alpha is not a colour component.
The GL texture is a normalized 16-bit texture, not an integer texture. With
ideal point sampling, a raw word `W` therefore starts as `W/65535`.

`pl_color_repr_normalize` returns the full-range scale
`65535/(64*1023)`. The enhancement sampler multiplies by that scale, so ideal
arithmetic gives:

```text
el_sample = W / (64 * 1023)
s = W / 64                         # native-code equivalent, possibly fractional
```

No integer shift or truncation to `W >> 6` occurs in this path. A raw-word step
of one remains a native-code step of 1/64 in the ideal arithmetic.

This is a numeric representation statement, not a complete texture-sampling
model. The ordinary Y416 EL plane declares `shift_x = -0.5`; the renderer folds
that into the sample rectangle before dispatching the sampler. Interpolation
can therefore change the value entering NLQ. Raw surface profiles are not
automatically the exact samples seen at the later shader coordinates.

## Metadata upload and residual formula

Let `b` be EL bit depth, `D` the coefficient denominator exponent, `O` the
neutral offset, and `S` and `T` the combined fixed-point slope and threshold.
The CPU upload performs these operations:

```text
el_scale = float(1 / (2^b - 1))
offset = float(el_scale * O)
slope = float(((2^b - 1) / 2^D) * S)
threshold = float((T - S/2) / 2^D)
```

For slope and threshold, the inspected implementation uses double-precision
coefficient calculations before assigning the float fields. The offset uses
the already rounded float `el_scale`. Shader parameters are three-component
float vectors.

The shader then evaluates:

```text
e = el_sample - offset
noise = 2^-22 * max(abs(el_sample), abs(offset))
if abs(e) <= noise:
    e = 0
residual = sign(e) * (abs(e) * slope + threshold)
reshaped_BL += residual
```

The coefficient fixture is `b=10`, `D=23`, `O=512`, `S=2048`, `T=0` and
maximum `1048576`. These scalar values match the verified frame-2296 coefficient
subset; no RPU payload or film pixels are included here. In ideal arithmetic,
outside the tiny guard:

```text
residual = (s - 512 - 0.5*sign(s - 512)) / 4096
```

At neutral the residual is zero. This equals the pre-floor standalone residual
in 16-bit correction units divided by **65536**, not 65535. For this fixture,
the uploaded slope `0.249755859375` and threshold `-0.0001220703125` are exactly
representable in binary32. The normalized offset is not exact.

## How narrow is the neutral guard?

With ideal normalization, the guard condition can be expressed directly in
native-code units as:

```text
abs(s - 512) <= 2^-22 * max(abs(s), 512)
```

Immediately below neutral, its width is `1/8192` native code, or `1/128` raw
Y416 word. Immediately above neutral, the width is slightly larger because the
maximum uses the sample itself: `32768/4194303` raw words, approximately
`0.00781250186265`. These are ideal-coordinate widths; the actual float
comparison is around the uploaded float offset.

For orientation only, a host calculation that rounds each UNORM conversion,
normalization multiplication and subtraction separately to binary32 gives:

| Raw word | Centred normalized value | Guard magnitude, approximately |
|---|---:|---:|
| 32767 | −0.0000152587890625 | 0.000000119326 |
| 32768 | 0 | 0.000000119326 |
| 32769 | +0.0000152587890625 | 0.000000119329 |

Thus this example guard removes cancellation-scale noise, not the neighbouring
raw-word values. It does not establish that the fractional values 511.75 or
512.25 should be neutral. Extending the algebra to those values gives residuals
with the opposite sign to their distance from neutral; that mathematical
behavior is not itself evidence of the licensed rule for fractional inputs.

The host illustration is reproducible without NumPy or a GPU:

```python
import struct

def f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]

scale = f32(65535 / (64 * 1023))
offset = f32(f32(1 / 1023) * 512)
for word in (32767, 32768, 32769):
    sample = f32(f32(word / 65535) * scale)
    centred = f32(sample - offset)
    noise = f32(2**-22 * max(abs(sample), abs(offset)))
    print(word, centred, noise)
```

This explicitly chosen arithmetic is not a GPU emulator. Texture filtering,
UNORM conversion precision, floating-point contraction and shader compiler
choices are not verified by this calculation.

## Bounds, addition and the next stage

The NLQ shader parameter structure contains offset, slope and threshold only.
`vdr_in_max` is examined when identifying trivial metadata, but no maximum
residual field is uploaded to this shader and there is no residual clamp in
`sh_dovi_compose_nlq`.

Before the addition, BL normalization and reshaping run; the reshaped component
is bounded by its metadata pivot endpoints. The EL residual is then added as a
float. There is no immediate 17-bit integer residual floor, 12-bit composition
round, or 12-bit composition bound in this shader section. Next comes the
metadata nonlinear matrix/offset transform, followed by the PQ/linear-matrix/PQ
conversion shown in the cited source lines. Nonnegative domain clamps in that
later conversion are not the metadata residual-maximum bound. Later rendering
and output quantization are outside this arithmetic audit.

Our standalone integer reference is based on the fixed-point reconstruction
process in [ETSI GS CCM 001 V1.1.1, clauses 5.4.3.2–5.4.3.3](https://www.etsi.org/deliver/etsi_gs/CCM/001_099/001/01.01.01_60/gs_ccm001v010101p.pdf).
Its input contract and the informative Annex-B resampling path do not establish
a normative extension to arbitrary fractional Y416 samples. Consequently a
future CPU shader-arithmetic model must remain separately labelled from the
integer reference, the actual GPU implementation and licensed-player behavior.
No new dead zone, rounding policy or renderer change follows from this audit.
