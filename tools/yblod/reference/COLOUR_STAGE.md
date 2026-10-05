# Explicit scalar colour-coordinate component

`colour_stage.py` is a reusable standard-library-only float64 component. It
does not import NumPy, the older colour helpers, a renderer or hardware code.
It accepts reconstructed or separately expanded 12-bit component triples and
returns the intermediate coordinates and quantized target codes. Streaming
conversion is lazy and uses a constant-size working set per sample.

## Choices callers must supply

`ColourConfig` requires source and target matrices, offsets, an explicit PQ
domain policy and the project code scale of4096. `from_dm` extracts only the
supported uncompressed, full-range12-bit source metadata subset. It validates
types and finite values, not full RPU semantics, provenance or frame identity.
Source matrices need not be invertible; target matrices must be invertible.
Configuration is copied into immutable tuples and target inverses are computed
once, not once per pixel.

No target is chosen from a TV or silently supplied by this module. Tests
explicitly use the project's existing target-coordinate matrices. Those
matrices,4096 scaling and output quantization remain a project transport
convention, not proof of licensed Dolby output.

The two supported policies are:

- `reject-outside-unit`: reject any PQ input outside0..1. This detects domain
  excursions; it does not perform tone mapping or select a correction.
- `extend-positive-negative-to-zero`: retain the older diagnostic's positive
  extension, map negative PQ inputs to zero, and reject decode poles/nonfinite
  results. This is an explicit experimental continuation, not an established
  licensed-player rule outside the published PQ domain.

The policy applies to PQ operations in both source decoding and target encoding.
The module does not insert an RGB gamut clamp. Final target coordinates are
rounded using `floor(value*4096+0.5)` and bounded to0..4095; that output-code
bound is distinct from source reconstruction limits or TV brightness adaptation.

## Order and scope

The component subtracts source offsets, applies the source nonlinear matrix,
decodes PQ, applies the source linear matrix, changes to the explicitly supplied
target linear basis, encodes PQ, changes target nonlinear coordinates, adds
target offsets, and finally quantizes. Every intermediate remains available in
an immutable `ColourResult` for inspection.

Fractional component values are allowed for a **separately declared chroma
expansion**; raw input values must remain in0..4095. This does not choose an
enhancement-layer fractional transport contract. Chroma expansion, active-area
masking, tunnel packing, metadata embedding, HDMI signaling and display mapping
are outside this component. It is scalar validation code, not a real-time GPU
implementation or a complete Dolby Vision engine.

## Evidence

Tests compare published-domain PQ results and eight synthetic colour triples
with the separate60-digit Decimal oracle. Another792 combinations compare
intermediate values (with stated float tolerances) and exact target codes with
the older NumPy diagnostic across identity and nonidentity source matrices.
These establish the declared arithmetic, not the correctness of out-of-domain
policies on licensed devices. Scalar evaluation and NumPy can differ slightly
near rounding boundaries; these fixtures do not prove universal byte equality.

The streaming bridge also checks576 separately expanded synthetic pixels from
the assembled runner: scalar conversion yields equal target codes and packed
bytes to the existing colour path. Bilinear chroma expansion and packing are
still the old diagnostic helpers, not independent replacements.

On Ollie, 576 reference tests plus8 accuracy tests passed (584 total, no skips)
with a512 MiB ceiling and job swap disabled. The component's eight tests run
without NumPy except for the explicitly optional older-path differential check.

Next build a bounded colour-frame adapter with explicit source identity,
chroma expansion and target configuration. Keep the old implementation as a
comparison path; do not change production defaults based on these fixtures.

## Minimal synthetic example

With this tools directory on the Python import path:

```python
from colour_stage import ColourConfig, convert_sample

identity = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
cfg = ColourConfig(identity, (0, 0, 0), identity,
                   identity, (0, 0, 0), identity,
                   pq_policy="reject-outside-unit", code_scale=4096)
assert convert_sample((2048, 2048, 2048), cfg).codes == (2048, 2048, 2048)
```

This explicitly identity-to-identity example is synthetic, not the project's
Dolby transport target.
