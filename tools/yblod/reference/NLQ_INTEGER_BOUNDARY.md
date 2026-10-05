# Integer input boundary: alternatives, not a selected correction

The integer reference expects whole enhancement-layer codes. The scaler can
produce fractions between those codes. This diagnostic makes three possible
ways of crossing that boundary explicit: round down, round to nearest with
halfway values rounded up, and round to nearest with halfway values rounded to
the even integer. None is selected as the licensed or preferred behavior.

`nlq_integer_boundary.py` tests all 1024 integer anchors, a 4093-point grid of
anchors and quarter-code fractions, and every raw word within two codes of
neutral (257 points). Every policy uses the unchanged integer reference after
its declared input rounding. Integer anchors must agree exactly.

The report separately compares those results with the earlier **hypothetical**
fractional formula and final-floor extension. Differences against those models
are not errors against Dolby hardware. Final 12-bit values use a synthetic
fixed base-layer value of 32768, not a decoded movie base layer and not the
production float shader's output.

## Domain and interpretation

The shared experimental domain is raw words 0 through 65472, corresponding to
native codes 0 through 1023 before rounding. This is an experiment restriction,
not the 16-bit storage limit or a proposed clipping rule. A separate candidate
calculation covers the full stored-word range and reports whether its rounded
result is valid. At raw word 65504, nearest policies propose code 1024; that
candidate is reported, never silently clipped or passed to the reference.

Input rounding, the reference's residual accumulator floor, and its final
output rounding are different operations. Rounding input creates a much wider
zero-correction region than the current shader's tiny numeric neutral guard.
That does not establish that either behavior is the right transport contract.
See `NLQ_SHADER_AUDIT.md` for the source-defined shader differences.

## Reproduce

```sh
python3 nlq_integer_boundary.py NEW-REPORT.json
python3 -m unittest test_nlq_integer_boundary
```

The public synthetic report is `results/nlq-integer-boundary-v1.json`.
It pins the tool and helper source bytes and reports transition points, exact
bias histograms, monotonicity, sign checks, and sampled zero-correction spans.
Sparse whole-range samples are not treated as an exhaustive raw-word sweep.
No new capture, hardware job, production change, fitted dead zone, or SK4-match
claim is involved.

Verified on Ollie with a 512 MiB memory ceiling and job swap disabled: 514
reference tests and 8 accuracy tests passed (522 total, no skips). The reference
suite includes all seven new boundary tests and the compiled pre-GPU guards.

Next, test the metadata residual-maximum boundary independently and decide the
new engine's input precision contract from source/spec evidence and explicit
tests, rather than choosing whichever of these alternatives looks closest to
a captured picture.
