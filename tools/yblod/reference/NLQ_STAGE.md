# Reusable integer enhancement-correction stage

`nlq_stage.py` is the first extracted, reusable correction component for the
standalone engine. It has no dependency on Kodi, libplacebo, a GPU, NumPy, movie
frames, or the experimental shader-comparison tools. It is not a complete Dolby
Vision renderer and is not connected to existing playback.

The input contract is intentionally narrow: whole, native enhancement-layer
codes and explicitly supplied fixed-point parameters. The module does not
silently round scaler output or choose one of the fractional-input policies
examined in `NLQ_INTEGER_BOUNDARY.md`.

## Contract

Configuration is immutable and validates input depth (8 or 10), coefficient
denominator, native neutral offset, and nonnegative slope, threshold and maximum.
Boolean values and floats are not accepted as integers. Coefficient validation
matches the existing standalone manifest envelope; it is not full RPU or Dolby
bitstream validation.

For each input sample, the component:

1. Returns zero for an exactly neutral code.
2. Computes the signed correction with the declared depth and coefficients.
3. Applies the metadata maximum to the accumulator.
4. Floors the signed result to the reference's correction units.

The correction remains signed. This stage does not map the base layer, add the
layers, round to an output depth, convert colour, scale or expand chroma. Integer
accumulators use Python's arbitrary precision; a later native/GPU implementation
must explicitly establish its accumulator width and rounding behavior.
Correction units do not imply 16-bit storage: the accepted manifest envelope
can produce values outside signed 16-bit and signed 17-bit ranges. No unstated
storage clamp is applied.

The streaming helpers avoid materializing a frame and process supplied sample
iterables lazily. Callers remain responsible for frame identity, dimensions,
channel-specific configuration and upstream buffer ownership.

The correction maximum comes from content metadata, not the TV's EDID. Later
brightness/colour adaptation can use display capabilities, but it cannot
generally replace a bound on the enhancement correction before the layers are
combined. This module therefore has no display-capability input.

## Use

```python
from nlq_stage import NLQConfig, iter_corrections

config = NLQConfig.from_mapping(
    {"offset": 512, "slope": 2048, "threshold": 0, "maximum": 1024},
    bit_depth=10, denominator=23,
)
assert list(iter_corrections([510, 511, 512, 513, 514], config)) == [-8, -8, 0, 8, 8]
```

That deliberately small maximum is an arithmetic fixture, not movie metadata.
Run with this tools directory on the Python import path. For streamed rows,
consume each yielded correction row before advancing a shared upstream source.

## Independence and verification

The implementation does not call `reference.inverse_el`. The existing reference
remains unchanged and supplies a separate comparison implementation. Tests cover
every native sample in varied 8-bit and 10-bit fixtures, explicitly fixed answers,
zero and binding maxima, signed flooring, invalid configuration and lazy input
consumption. Agreement is arithmetic evidence, not a licensed-player match.

On Ollie, 527 reference tests and 8 accuracy tests passed (535 total, no skips)
with a 512 MiB memory ceiling and job swap disabled. The six component tests
include 107520 sample comparisons over 168 configurations and independent
literal boundary answers.

`NLQ_LIMIT_BOUNDARY.md` records why the accumulator limit and operation order are
explicit here. `NLQ_SHADER_AUDIT.md` describes the inspected older float shader;
its transport and evaluation rules are not silently adopted by this component.

Next connect this stage to a bounded standalone composition path, retaining the
existing reference as an oracle. Fractional scaler input remains a separate
contract decision; Intel/AMD offload can remain upstream without making the
correction stage vendor-specific.
