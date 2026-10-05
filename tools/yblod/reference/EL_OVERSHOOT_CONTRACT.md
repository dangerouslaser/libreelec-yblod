# Enhancement-layer overshoot: an unresolved integration boundary

2026-10-05. Source/specification audit only. No arithmetic, clamp, playback,
hardware setting or production default was changed.

## Plain-language conclusion

An enlargement filter can produce a value slightly brighter than either of its
neighbours. That is filter overshoot, not a television brightness limit.

Our two standalone interfaces currently disagree about which such values they
accept: the example resampler preserves them in a wider container, while the
integer composer accepts only whole values within its declared input depth.
Connecting those interfaces blindly is therefore unsafe. Silently cutting off
the extra values, or simply widening the composer, would each select a new
policy that the existing tests do not justify.

The specification provides a stronger input-depth constraint than a storage-type
label alone, but does not specify the missing adapter operation. The current
shader's willingness to continue beyond normalized one is an implementation
observation, not proof that this is the licensed reconstruction rule.

## What the primary specification establishes

[ETSI GS CCM 001 V1.1.1](https://www.etsi.org/deliver/etsi_gs/CCM/001_099/001/01.01.01_60/gs_ccm001v010101p.pdf)
is the source; printed page numbers follow. Its exact PDF SHA256 is
`c711442055e73c88be8380317c388d5d9f1992a0fd1fc4bc1f549566a4685b2c`.

- Clause 5.2.2(f), p13, requires each composer input sample to need 8 or 10
  representation bits. It does not spell out `sample <= 2^EL_bit_depth-1`.
  Nevertheless, positive integer 1095 needs 11 bits: the constraint concerns
  sample representation, not merely a storage-container label.
- Clause 4 note 1, p11, places resampling before composition but explicitly
  makes resampling non-normative.
- Informative Annex B.3, p37, describes the EL resampler output as the same
  data type as its input, yet its filter equations clip to 0–65535. Negative
  filter coefficients can produce results exceeding a native 10-bit maximum.
- Clause 5.4.3.2, pp20–21, starts inverse quantization by subtracting the offset
  from the supplied sample. No separate 0–1023 input clamp appears there. Its
  explicit metadata-dependent limit bounds the residual accumulator instead.
- Clause 5.4.3.3, p21, separately bounds the final reconstructed output after
  addition and rounding.

Thus the normative input constraint and the informative filter example leave
an integration question; the example does not override the input constraint
or establish a mandatory pre-NLQ clamp. No fractional-input rule follows.

## A reproducible counterexample in our code

The synthetic native-code input below contains only legal 10-bit values:

```text
   0  1023
1023     0
```

At the top-right vertically enlarged sample, replicated-edge taps in our
Annex-B implementation yield `(137*1023 + 64) // 128 = 1095`.
The unsigned-16 storage bound preserves 1095; the subsequent horizontal even
sample copies it. This is a code-derived example, not a captured film pixel or
a measurement from licensed hardware.

The existing literal regression is
`test_native_annexb_probe.py:70–74`. `native_annexb_probe.c:36–80` performs the
specified rounding/storage bounds and preserves the intermediate result.
Conversely:

- `prepare_frame.py:229–230` rejects a prepared result outside the declared
  native depth rather than adding an undocumented clamp.
- `nlq_stage.py:59` validates the whole input sample against that depth.
- `native_composer.c:201–211` rejects an out-of-domain scalar EL sample;
  `:311–316` checks every chunk sample before writing outputs.

That rejection is the current API contract. It is not a claim that every
overshooting resampler must discard the overshoot in this particular way.

## Do not confuse native values with packed Y416 words

For the inspected 10-bit/six-fraction-bit Y416 route, these are different units:

| Representation | Example or upper bound | Meaning |
|---|---:|---|
| Whole native 10-bit composer input | 1023 | Current integer API maximum |
| Native-valued unsigned-16 resampler output | 1095 | Counterexample above; rejected by that API |
| Raw unsigned-16 Y416 word `W` | 65535 | Maximum representable surface word |
| Q6 native-equivalent value `W/64` | 1023.984375 | Maximum in this particular packed route |

The nominal native endpoint 1023 occupies raw word 65472. Words 65473–65535
therefore carry above-endpoint fractions; retaining their low bits matters.
Our raw-word readers and sampling diagnostics must preserve them, not secretly
truncate or clamp them to 65472.

However, native 1095 would require raw word 70080 under that same Q6 scaling.
It cannot be stored unchanged in this carrier. Keeping an Annex-B result as a
native-valued unsigned-16 plane and keeping a Y416 surface's raw words are two
different preservation contracts. Reinterpreting one as the other is wrong.

For the inspected texture route, ideal UNORM conversion and representation
scaling give `W/65535 * 65535/65472 = W/65472`. At raw 65535 this exceeds one.
This algebra describes units, not an exact binary32 evaluation oracle; the
separate conversion, filtering and multiplication can round differently.
See [the sampling source audit](EL_SHADER_SAMPLING_AUDIT.md) and
[the measured synthetic texture diagnostic](NATIVE_TEXTURE_PROBE.md).

## Inherited and current floating-point shader behavior

The repository's original imported engine commit
[`08245584de834b6e42b952106c033a2b4841fef0`](https://github.com/dangerouslaser/libreelec-yblod/commit/08245584de834b6e42b952106c033a2b4841fef0)
is labelled as the CroqueMr engine import. Its libplacebo package pins
`e2972fdd09adacd383656738d7d280f0cd84a761`. Its tracked
`libplacebo-9910-4.patch` already contains the neutral-noise guard; this audit
does not attribute that existing guard to later work or claim to cover every
historical Croque version.

Both the pre-patch expression shown in that patch and the current inspected
NLQ expression subtract the offset and evaluate a signed slope/threshold
formula. Neither includes a [0,1] input clamp. The added guard only zeros a
tiny neighbourhood of the neutral offset; it is not an upper-endpoint clamp.

In the inspected build source:

- `src/renderer.c:1668–1673` multiplies the sampled EL by its representation
  scale and assigns the components without a postscale bound.
- `src/shaders/colorspace.c:106–149` consumes that result, applies the neutral
  guard and adds the floating-point residual. A finite sample above one is
  not rejected or limited to one by this code.
- No maximum-residual parameter is applied in that shader section. This is
  distinct from the input-range issue; see [the NLQ audit](NLQ_SHADER_AUDIT.md).
  A later colour/output clamp would not be equivalent to a pre-NLQ clamp.

This identifies inspected source behavior only. It does not prove the loaded
Kodi binary's identity, the active runtime path, an actual overshooting movie
sample, or licensed-player correctness. No new GPU dispatch was used for this
audit, and no source-matching offset or SK4-based adjustment is proposed.

## Source pins and reproducibility

The inspected reconstruction worktree HEAD was
`a6bb9ae3a5ac3aba37b7adb7f849acdb9ac6f745`. The separate existing patched
libplacebo build-source directory is versioned with the package commit above;
these file hashes, rather than the package name alone, identify its contents.

| File | SHA256 |
|---|---|
| `prepare_frame.py` | `1598949151e10b3fbc273eadb80f40f9edbc3d01215d7c90acfe2cfe56f7bab9` |
| `nlq_stage.py` | `43aea713446a3e703687a4e79054c2fb22b811693f8ed7b99da8c8951c83fc7e` |
| `native_composer.c` | `29d8eb549bf00a752ec3d28c99b9a16ce8a256faceec91411b89a46fc3612369` |
| `native_annexb_probe.c` | `c6d4655e3ed07c14b81de86b8e6f1da0aa3e009dc182a3d529230777a342f124` |
| `test_native_annexb_probe.py` | `f9966f1dfcdc8e06fa39d1a3b2ebc55084436fb52c5abb233fbea1829979ac39` |
| Patched libplacebo `src/renderer.c` | `b4318cb4ee2199d0b7ed2202b5e950d2a9dcbb368300e9d1d5d9fa8d3f65e1f5` |
| Patched libplacebo `src/shaders/colorspace.c` | `5961adebdc5f4768eb6cf28560f9cb1143c65d3cfbe6be089097347dc232ebcf` |
| Tracked `libplacebo-9910-4.patch` | `69c953b17a4a54b637d1dea07e56a203a14bd437b7e1b8a95bcf769766131070` |

Recheck hashes and numbered lines with `sha256sum FILE` and `nl -ba FILE`.
The patch lives under
`packages/addons/addon-depends/multimedia-tools-depends/libplacebo/patches/`.

Before integrating a scaler, its adapter needs an explicit value-domain and
fractional-precision contract. Keep above-endpoint observations visible, report
unsupported inputs, and compare any proposed adapter policy against independent
arithmetic expectations. Do not silently reinterpret storage, introduce a
clamp, or extend the proven integer API on the strength of this audit alone.
