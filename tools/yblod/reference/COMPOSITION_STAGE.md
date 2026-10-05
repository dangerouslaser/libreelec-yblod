# Reusable mapped-base plus enhancement composition

`composition_stage.py` connects the reusable integer enhancement correction to
the final addition, rounding and output bound. This is a standalone component,
not Kodi wiring or a complete renderer. The existing reference remains unchanged
as a separate comparison implementation.

## Inputs and order

The base-layer input is **already mapped** to integer units in 0 through 65535.
This module does not implement base-layer mapping. Enhancement input is a whole
native code with a validated `NLQConfig`; fractional scaler values are rejected,
not silently rounded.

The combined path runs the correction stage, adds the signed correction to the
mapped base value, rounds once to the explicitly supplied 10-bit or 12-bit output
depth, then bounds the final output. Corrections and sums are not prematurely
clipped to an unsigned or 16-bit range. Halfway output values round toward
positive infinity, including when the signed correction is negative.

The lower-level `compose_residual` accepts an already calculated signed integer
correction. The combined `compose` uses `nlq_stage.correction`; it does not call
the old reference. `iter_composed` consumes paired iterables without buffering a
frame. Unequal lengths raise an error rather than silently truncating via `zip`.

`iter_base_only` is the explicit residual-disabled path. Missing enhancement
input is not interpreted as permission to fall back to base-only rendering.

## Use

```python
from nlq_stage import NLQConfig
from composition_stage import iter_composed

config = NLQConfig(10, 23, 512, 2048, 0, 1024)
pixels = iter_composed([32768, 32768, 32768], [511, 512, 513], config, 12)
assert list(pixels) == [2048, 2048, 2049]
```

The small maximum above is deliberately synthetic. Run with this tools directory
on the Python import path. A streaming mismatch or invalid later sample can be
discovered after earlier outputs have been yielded. A future file/HDMI adapter
must handle incomplete output appropriately and must not publish a completion
report until all input has been consumed successfully.

## Integration evidence and remaining scope

`test_composition_integration.py` reconstructs tiny synthetic bundles with the
unchanged reference and compares the new component's output with its complete
Y/Cb/Cr reconstructed planes. It covers both output depths, separate component
parameters, binding limits, and explicit base-only operation with no enhancement
files. **Mapped base planes still come from the reference**: this isolates the
new correction/composition stages, not an independent base mapper or end-to-end
engine. The old bundle runner still loads whole planes; these tests do not make
that runner bounded-memory.

On Ollie, 537 reference tests and 8 accuracy tests passed (545 total, no skips)
under a 512 MiB memory ceiling with job swap disabled. The seven composition
tests include 200192 scalar comparisons with the unchanged reference; three
additional tests compare synthetic bundles across both output depths.

Frame identities, dimensions, metadata association, MMR guide preparation,
decoding, scaling/chroma expansion, colour conversion, HDMI metadata and display
adaptation remain outside this module. TV capabilities do not set its correction
maximum. There is no new SK4 matching claim or licensed Dolby certification.

Next supply independent base mapping and a bounded adapter with explicit frame
validation, then compare larger prepared inputs against the reference before
GPU implementation or playback integration.
