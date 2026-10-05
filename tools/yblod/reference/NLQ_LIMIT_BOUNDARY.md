# Metadata correction limit: isolated arithmetic test

This diagnostic asks one narrow question: does the inspected shader's omission
of the metadata correction limit produce different arithmetic when that limit
is reached? It does not test a licensed player, a decoded movie, or the loaded
GPU shader. No playback behavior is changed.

The integer reference already has independent limit tests. The new
`nlq_limit_boundary.py` compares that unchanged reference with the exact-real
algebra of the inspected shader, documented in `NLQ_SHADER_AUDIT.md`. The source
shader has no uploaded maximum field. A separately labelled capped version of
its ideal algebra is a diagnostic alternative, not an implemented fix.

## Why an artificial fixture?

The verified frame-2296 coefficients have a maximum of 1048576. That limit is
not reached anywhere in the valid native-code range 0 through 1023, so the
existing fixture cannot distinguish capped from uncapped behavior.

The new fixture retains offset 512, slope 2048, threshold 0, EL depth 10 and
coefficient denominator 23, but sets maximum to 1024. This is deliberately an
**arithmetic fixture**, not an assertion that an encoded Dolby Vision stream
with these parameters satisfies every semantic constraint. Accepting a number
in our manifest validator alone does not establish bitstream conformance.

The [FFmpeg RPU parser](https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/dovi_rpudec.c)
and [dovi_tool NLQ reader/writer](https://github.com/quietvoid/dovi_tool/blob/main/dolby_vision/src/rpu/rpu_data_nlq.rs)
represent the maximum, slope and threshold as separate coefficient fields.
This supports testing the maximum independently; it does not prove that the
chosen scalar values form a complete conforming RPU or encoded stream.

In the reference's 16-bit correction units, the artificial limit is 8. A sample
one whole code from neutral reaches exactly +8 or -8; two whole codes away
would yield +24 or -24 without the cap, but the reference limits it to +8 or -8.
The report distinguishes touching the limit from actually changing a value.

A secondary maximum of 1025 checks operation order. Its exact limit is
1025/128 correction units. Clamping first and then flooring gives +8 and -9,
not a symmetric pair of integers. A clamp on an already rounded residual is
therefore not generally equivalent to the integer reference's operation.

## Scope and reproduction

```sh
python3 nlq_limit_boundary.py NEW-REPORT.json
python3 -m unittest test_nlq_limit_boundary
```

The report is `results/nlq-limit-boundary-v1.json`. It contains compact aggregate
results and selected exact boundary values; full sweep rows are hashed rather
than published redundantly. Source identities and the ideal normalization are
explicit. Fractional input comparisons remain hypotheses about an input
contract, not a normative fractional extension of the integer reference.

Neither finite-float texture sampling nor actual GPU evaluation is emulated.
No final 12-bit picture values or SK4 matching scores are reported. This test
isolates the correction stage before addition and later colour conversion.

The binding fixture changes 1021 of 1024 integer-anchor corrections and 256
of 385 samples in the dense near-neutral raw-word sweep. The actual-maximum
control changes zero in either set. These are deliberately chosen test counts,
not movie error frequencies. The generated report reproduced exactly during
independent review. On Ollie, 521 reference tests and 8 accuracy tests passed
(529 total, no skips), with a 512 MiB ceiling and job swap disabled.

The next decision is whether and how to carry the metadata maximum through the
new engine's correction stage, while retaining a clearly declared precision
boundary. Actual playback impact needs applicable metadata and a separate
integration test; this synthetic discriminator cannot establish it.
