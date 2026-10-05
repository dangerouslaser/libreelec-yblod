# Scaler differences through reconstruction arithmetic: bounded diagnostic

This tool separates three things: measured raw EL samples, the declared ideal
sampling hypothesis, and a **hypothetical fractional-input continuation** of
our standalone integer NLQ arithmetic. It is not a licensed-player or finite-float
playback-shader emulator, and it does not establish which fractional transport
contract a production pipeline should use.

`reference.py` accepts integer enhancement-layer codes. Its fixed-point formula
and final floor remain unchanged. The new `nlq_scaling_sensitivity.py` retains
rawY416 words as exact `word/64` fractions; it reports both the pre-final-floor
algebraic continuation and the final-floor extension explicitly. Integer inputs
are exhaustively compared with the existing reference. No bit truncation,
neutral dead-zone, fitted gain/phase, pipeline default or colour limit was added.

The coefficient fixture matches the verified frame2296 NLQ subset:
offset512, slope2048, threshold0, maximum1048576, ELdepth10, denominator23.
No copyrighted frames, layers or complete RPU payloads are included.

## Actual measured pairs, hypothetical fractional arithmetic

The input is `results/intel-y416-large-v11.json`: the completed full-size
ascending-band measurement. Canonical source grids, raw-word layout, stable
profiles and exact input/scorer hashes are checked. The comparison uses the
**predeclared pixel-centred coordinate hypothesis**, not SK4 ground truth.

All1536 measured scaled profile pairs are included in aggregate histograms:
128 samples on each Yaxis,320 on each Cb/Cr axis. Measured input errors are
±1/2code Y and±1/4code chroma. In the hypothetical arithmetic these produce
equal-count residual errors±8 and±4 respectively, in16-bit correction units,
with zero mean signed error. No sample's actual or expected value crosses
neutral, is exactly neutral, or lies within±1/2code of neutral. Closest actual
distances are1.5Y and1.25chroma codes. This dataset therefore establishes only
same-branch sensitivity for this diagnostic.

With an explicitly **synthetic fixed mapped-BL value32768**, final12-bit code
differences were−1or0, equally often, with no clipping. This is not a real-frame
prediction, perceptual colour score or error frequency for movie playback.
The mapped-BL value is not measured from the source movie; spatial interpolation,
shader normalization/noise guards and subsequent colour conversion are omitted.

Evidence: `results/nlq-scaling-measured-sensitivity-v2.json`, which pins exact
measurement-report bytes, integer reference, geometry helper and tool source.

## Separate near-neutral and boundary synthetic fixtures

Thirty synthetic EL-error placements also cover the same error magnitudes,
neutral and fractional values on either side, with five independent mapped-BL
anchors0/8/32768/65520/65535. Separate clipping counts and interior results avoid
concealing errors in saturation. These are chosen fixtures, not video rates.

Away from neutral/bounds, this coefficient fixture's continuation has linear
sensitivity16 correction units per native EL code. Close to neutral the naive
continuation is not globally linear: it gives `N(511.75)=+4`, `N(512)=0`,
`N(512.25)=−4`. This sign reversal/discontinuity is **model behavior**, not an
established Dolby rule or an observed crossing in the actual gradient corpus.
It must not justify dropping fractional bits, adding a clamp/dead-zone, or
tuning output to the SK4. The normative fractional result remains explicitly
unknown in the report. The actual shader's tiny neutral guard is not emulated.

## Reproduction and next decision

```sh
python3 nlq_scaling_sensitivity.py NEW-REPORT.json \
  --measured-report results/intel-y416-large-v11.json
```

Next compare independently declared integer and fractional processing contracts
on neutral/boundary fixtures, keeping normalization and existing shader sampling
separate. Only then select a precision boundary for the new engine. Existing
playback and reconstruction defaults remain unchanged; no SK4-match improvement
or Dolby conformance is claimed. The subsequent explicit alternatives are
documented in `NLQ_INTEGER_BOUNDARY.md`; the inspected float shader's separate
contract and limitations are documented in `NLQ_SHADER_AUDIT.md`.
