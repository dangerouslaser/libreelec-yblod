# Enhancement texture sampling: source audit

2026-10-05. Read-only inspection; no playback, shader, driver or display changes.

## Plain-language finding

The current inspected playback path does more than read the scaler's output.
For the ordinary full-size enhancement surface, it reads halfway between two
neighbouring horizontal pixels. With the supported linear texture format, this
blends their values before enhancement reconstruction. It applies to all three
colour components in the packed surface, including luma.

The small fractions in those values remain present. There is no conversion back
to whole 10-bit codes at this sampling boundary. Therefore a downloaded scaler
word is not necessarily the value the later reconstruction shader receives.

These conclusions describe pinned source and the explicitly stated geometry
below. They do not prove that the loaded Kodi binary follows this source, that
the hardware import has the assumed component layout, or that the shift is the
correct Dolby registration. The code comment's explanation of hardware phase
is an implementation assumption, not independent evidence about every scaler.

## Inspected sources

The reconstruction repository was at `1f0acfa991b2b89eb3740831e99b32a1840b9189`
when the tracked patch was read. Subsequent documentation/experiment commits do
not identify a loaded Kodi binary. The existing build trees on Ollie were:

```text
/home/bryan/Projects/libreelec-yblod/build.LibreELEC-Generic.x86_64-13.0-devel/build/
  kodi-22.0rc1-Piers/
  libplacebo-e2972fdd09adacd383656738d7d280f0cd84a761/
```

`K/` and `P/` below denote those Kodi and libplacebo directories. Hashes identify
the actual patched files, not merely an upstream version label.

| Source | Relevant lines | SHA256 |
|---|---|---|
| K/tools/dvbridge/dvbridge_gl_frame.c | 35–66 | `7d5b814e09cfe30aaaab4be0eed7c9eea3f214bf783682a56587cb8a4c39de24` |
| K/tools/dvbridge/dvbridge_vpp.c | 142–155, 177–180, 254–266 | `d6e7df80d945f7fcf6c7a3ad26a4b72b568a982f171ed98d66e5be59946750a0` |
| K/tools/dvbridge/dvbridge_render.c | 259–263, 275–300 | `f829f1ff5467892391640fb4f2368202cdb4e8decc9e46b151b5ce81cbe640e0` |
| K/xbmc/cores/VideoPlayer/VideoRenderers/DVBridgeGLES.cpp | 301–314, 417–481 | `14cbbda4369274a6eaa0a811fcc99e7594dfbb89ced8b4f6824b8c718554f7ca` |
| P/src/renderer.c | 207–215, 607–721, 796–798, 1575–1678 | `b4318cb4ee2199d0b7ed2202b5e950d2a9dcbb368300e9d1d5d9fa8d3f65e1f5` |
| P/src/shaders/sampling.c | 54–77, 136–145, 277–287 | `d73240ec03cdf079a359a0284ba87c91de857f88295971aff5edbf2da53b1c02` |
| P/src/shaders.c | 513–560 | `12d31e91c486aa58c6aec632822015039bbcd59bf981d7301c241e59b1afd547` |
| P/src/opengl/formats.c | 105, 221 | `a57ec2a106860a6e7e2ffb0ed992556c9146a37295e5a4790633c93594f9e0c6` |
| P/src/opengl/gpu_pass.c | 438–463 | `59c21e7b0853e9cd2de96fec6c93c6e68910dbe4665b9607107dd95d017f00f8` |
| P/src/colorspace.c | 27–45, 177–220 | `0099300821d9960dd291f2b6ac22eb5779e95326ae327c488030268e8c02f5e3` |
| P/src/include/libplacebo/renderer.h | 322–323, 377–383 | `2dfb2585571f7b09806d7c981c939da8f8c39c818372d96a48d7cc78523e07cd` |
| P/src/include/libplacebo/gpu.h | 658–668 | `76c4c95b8d6f7dd0512262d6e57d274725df28d6516fd2b0b247e9bcd442d0cf` |

The tracked [QSV offload patch](https://github.com/dangerouslaser/libreelec-yblod/blob/1f0acfa991b2b89eb3740831e99b32a1840b9189/projects/Generic/patches/kodi/kodi-9999-yblod-01-qsv-offload.patch#L125)
contains the import declarations at lines 125–155 and VPP texture/parameter
setup at lines 557–595 and 669–679. Its SHA256 is
`209e16d08cc04a15c34dbb182f8fde284004fc6aa0bc2ad58bd743caa6eb79ff`.
Reproduce locations with `sha256sum FILE` and `nl -ba FILE`; do not apply these
line numbers to an unverified source version.

## Format, component mapping and normalization

The bridge requests a VAAPI Y416 surface with `VA_RT_FORMAT_YUV444_12`, reduced
range on both sides, BT.2020, input chroma LEFT/vertical-centred, and default
scaling quality. Output chroma location and pipeline hint remain zero in the
zero-initialized parameter structure. These are requests, not proof of the
hardware's selected filter or word precision.

The texture wrapper declares `GL_RGBA16` (`0x805B`), a normalized unsigned
16-bit format, rather than `GL_RGBA16UI`. The first three texture channels are
mapped to Cb, Y, Cr; alpha is not used in EL composition. The representation
declares storage depth 16, colour depth 10, and bit shift 6. It does not discard
the six low bits. A code comment describing 12 significant bits is not a gate
that validates or clears low bits.

Unsigned normalized conversion divides a stored 16-bit word by `2^16−1`, not
by 65536 or 65472. This follows OpenGL's normalized fixed-point conversion rule;
the GLES norm16 extension introduces the corresponding normalized formats.
See [OpenGL 4.6 §2.3.5.1](https://registry.khronos.org/OpenGL/specs/gl/glspec46.core.pdf)
and [EXT_texture_norm16](https://registry.khronos.org/OpenGL/extensions/EXT/EXT_texture_norm16.txt).

The inspected enhancement frame starts with zero/unknown system and levels;
the wrapper sets its bit encoding. Kodi replaces the **base** representation
with mapped Dolby metadata, not the EL representation. The EL is copied and
acquired without such a replacement. In this source, unknown system with
unspecified levels takes the full-range normalization branch. Consequently,
in ideal arithmetic:

```text
texture-normalized value = filtered raw word / 65535
representation scale     = 65535 / (64 * 1023)
EL shader signal          = filtered raw word / 65472
native-code equivalent    = filtered raw word / 64
```

These denominators have different roles. Passing 65472 as if it were the
texture's UNORM conversion divisor would conflate two operations. Neither
operation is a whole-code quantizer. Actual filtering/conversion uses the GPU's
allowed finite precision; the equations are the ideal source interpretation.
In particular, separately rounded `float(float(W/65535)*float(65535/65472))`
need not have the same bits as `float(W/65472)`. A diagnostic must retain both
the texture result and the post-scale result, rather than compare only with a
collapsed single-division model. The specification's mathematical normalization
formula is not a promise of exact binary32 rounding at every implementation step.

## Coordinates and filter selection

`sample_el` starts from the BL crop. It obtains EL-to-BL reference ratios
`rlx,rly` rounded to integer or reciprocal-integer scale ratios, and each plane's
relative ratios `rrx,rry`. Its rectangle endpoints are:

```text
sx = layer_x + plane.shift_x / rlx
sy = layer_y + plane.shift_y / rly
EL rectangle = ((BL.x0-sx)*rrx, (BL.y0-sy)*rry,
                (BL.x1-sx)*rrx, (BL.y1-sy)*rry)
```

The extra layer siting is applied only along dimensions where the EL reference
is smaller than the BL reference. For an ordinary already-upscaled Y416 EL at
the same full raster size, all ratios are one and layer shifts are zero.
The plane's `shift_x=-0.5`, `shift_y=0` therefore makes a full crop's rectangle
`(0.5,0,W+0.5,H)`. For same-size output, output pixel `(x,y)` samples at texel
coordinates `(x+1,y+0.5)`, or logical centre indices `(x+0.5,y)`.

Under ideal linear interpolation, the interior value is therefore the average
of words at `(x,y)` and `(x+1,y)`. The right boundary clamps to the last texel.
OpenGL's texel-centre/linear-weight convention independently supports this
interpretation once the libplacebo rectangle is established; see
[OpenGL 4.6 §8.14, printed pages 260–261](https://registry.khronos.org/OpenGL/specs/gl/glspec46.core.pdf).
This is one packed plane: the coordinate applies equally to U, Y and V. The
rotated-EL layout instead declares `shift_x=+0.5`, giving logical `x−0.5`
under the corresponding same-size geometry; the base-rotated layout declares
zero and marks the base frame rotated. Do not generalize either simplified
formula to arbitrary crops, resizing or final display rotation.

The VPP import initially sets linear filtering and edge clamp. More importantly,
libplacebo sets sampling and wrap state again when binding the texture. A
zero-initialized plane address mode means clamp-to-edge.

There is a subtle selection detail: the same-size sampler-info path labels
itself `SAMPLER_NOOP`/`SAMPLER_NEAREST`, but `dispatch_sampler` handles NOOP by
jumping to its **direct** fallback. That calls `pl_shader_sample_direct` with
`BEST`, which selects linear filtering when the format advertises linear
support, otherwise nearest. The rgba16 format entries advertise linear support,
subject to actual backend capabilities. The source-derived half-blend is thus
conditional on that capability and this geometry, not inferred from the
misleading NEAREST label alone.

The bridge sets `plane_upscaler` to Gaussian, but starts from default render
parameters whose `correct_subpixel_offsets` is false. No override was found in
the inspected bridge. Consequently, the half-pixel shift alone does not select
the configured Gaussian filter on the same-size path. Smaller/nonoffloaded
planes or different crop/output sizes can select a different path.

## Requirements for the standalone sampling interface

Keep the following explicit and independently testable:

- Raw unsigned 16-bit storage and U/Y/V/A mapping, including low bits and alpha.
- Logical texel-centre coordinates versus normalized texture coordinates;
  no implicit extra half-texel shift.
- Declared nearest/linear filter and clamp-edge policy; no automatic phase fit.
- Raw-word interpolation, UNORM division by 65535, representation scaling,
  and the equivalent native-code division by 64 as separate concepts.
- Exact rational/dyadic host reference versus finite-precision GPU observation.
- No implicit integer-EL quantization or new neutral dead zone after sampling.

This provides a source-defined sampling model to test, not an endorsement of
the old shift or a production default. Existing raw-scaler measurements and
whole-code GPU arithmetic checks do not measure this GL sampling operation.
Runtime confirmation would separately require a pinned loaded build and a
bounded texture-sampling diagnostic with known words, coordinates, capabilities
and readback precision. No such work was performed for this audit.

## Proposed smallest GPU observation, not implemented

Use an isolated desktop OpenGL 4.3 compute context on the explicitly verified
render node, with the existing finite-fence/error/cleanup pattern. No window,
KMS, Kodi, decoder or VAAPI import is needed. Integer-64 support is not needed:
this test observes texture sampling and ordinary float arithmetic only.

Upload a tiny 8×2 `GL_RGBA16` texture with explicit U/Y/V/A word patterns, plus
an otherwise identical `GL_RGBA16UI` storage/control texture. Require the
UNORM format and linear-filter support, query compute/SSBO limits before
allocation, and explicitly declare nearest versus linear filtering and
clamp-to-edge. Keep texture dimensions powers of two so quarter/half logical
coordinates produce exactly representable normalized coordinates. At most 128
sample records and one bounded dispatch are enough.

The synthetic cases should include zero/65535 format endpoints; neutral 32768;
native-code neighbours 32704/32832; quarter-code neighbours 32752/32784; raw-word
neighbours 32767/32769; constant rows; alternating rows; distinct components;
and left/right border samples. Include both zero shift and the source-derived
ordinary half-pixel horizontal shift, labelled as separate declared cases.
These do not tune a phase to a licensed capture.

For each record, preserve uint32 bit patterns and decoded floats for:

1. Integer-control words and `texelFetch` UNORM values at declared neighbours.
2. Filtered UNORM sample from `textureLod`, before representation normalization.
3. Post-scale normalized EL signal, with the actual uploaded float scale bits.
4. Centered signal, neutral-guard magnitude, guard decision and guarded signal.
5. Signed pre-colour NLQ result using explicit uploaded offset/slope/threshold.

Record the actual uniform bits and shader source, including arithmetic order.
Do not replace the inspected expression with a newly simplified division or
force new contraction/precision rules and call it the playback shader.

The independent host oracle has two distinct roles: exact rational sampling
establishes coordinates/weights, while an explicitly sequential binary32 model
shows one possible rounding path. Report raw-bit equality, ULP differences and
absolute raw-word/native-code-equivalent errors separately. The ideal rational
and sequential-float results must not be labelled bitwise GPU truth.

Initial hard gates should cover exact integer upload/readback and component
order, successful finite completion, clean GL/EGL state, and finite outputs.
Exactly representable normalization endpoints 0/1 and deliberately zero-input
arithmetic controls provide useful bit-level checks. Other texture/filter/NLQ
comparisons should first be recorded with declared diagnostic tolerances,
not assigned an invented universal one-ULP conformance rule. In particular,
near the neutral guard, classify both branch decisions and the final value:
a discontinuous formula cannot safely use one blanket relative-error test.

This would observe a desktop synthetic texture path. Kodi's GLES context,
EGLImage/DMA-BUF import, negotiated capabilities, actual generated shader,
intermediate precision, crop/rotation and loaded build remain separate
questions. Even exact agreement would not establish those paths or licensed
Dolby behaviour. Implementation and a device run require separate approval.
