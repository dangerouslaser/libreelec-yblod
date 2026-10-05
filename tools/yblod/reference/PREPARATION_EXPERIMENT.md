# Native-layer chroma preparation experiment

This checkpoint isolates the explicit top-left-to-left input adapter used by
the standalone reference. The two filters sample the same native coordinates:
`linear` uses two rows, while `cubic128` uses four rows with negative lobes.
They retain the existing integer rounding and declared-bit-depth bounds.
Neither filter is claimed to be Dolby's proprietary implementation.

## Controlled cases

| Case | Base-layer filter | Enhancement-layer filter |
| --- | --- | --- |
| Unchanged baseline | linear | linear |
| Base only | cubic128 | linear |
| Enhancement only | linear | cubic128 |
| Both | cubic128 | cubic128 |

Hold the identified source frame, decoded layers, RPU, luma, MMR luma guide,
Annex-B reference enlargement, reconstruction arithmetic, direct output policy,
final chroma expansion, active rectangle and tunnel packing fixed. The EL
enlargement input boundary stays explicit in `el-scaling-job.json`; this does
not remove the intended Intel Quick Sync/supported-AMD backend boundary.

The default `--phase-filter` retains its existing meaning. Optional per-layer
overrides are explicit and recorded; mixed cases do not falsely claim a shared
filter. For example:

```sh
python3 tools/yblod/reference/prepare_frame.py /path/to/extraction \
  /path/to/NEW-prepared --phase-filter linear --bl-phase-filter cubic128
```

Using `--el-phase-filter cubic128` instead changes only the EL's native chroma
phase conversion **before** the unchanged reference enlargement.

## Baseline and interpretation requirements

Before scoring alternatives, regenerate the baseline and verify every prepared
and reconstructed plane and the entire packed output against the saved frame-
1943 baseline. A mismatch, bad hash, changed metadata/coordinates, or partial
stage must stop the experiment; do not silently select a new baseline.

Use the same saved overlay-free frame-1943 capture and active rectangle in all
cases. Preserve the GUI-plane-disabled and unverified-DMA qualifications from
[CAPTURE_REPEAT.md](CAPTURE_REPEAT.md). Report candidate-versus-baseline changes
as well as candidate-versus-capture scores. Do not fit offsets, choose new sample
exclusions, add clamps, or deploy a filter based on a smaller score on one frame.

This first experiment does **not** move enlargement across reconstruction, test
a hardware scaler, or establish the correct filter. In particular, moving a
quarter-row phase operation from native EL chroma to the doubled grid without
changing its coordinates would alter the physical shift. A later ordering
experiment needs an independently derived coordinate contract first.

## Current checkpoint

Per-layer controls are implemented, and all **20 preparation tests** plus **12
independent geometry tests** pass on Ollie under the 512 MiB hard cap with swap
disabled. The independent [oracle](preparation_oracle.py) evaluates the cubic
from exact endpoint values and slopes rather than copying production taps. Its
tests cover constants, ramps, impulses, edge replication, signed rounding,
overshoot/bounds, independent columns and FIR chunk boundaries.

The reference suite passed **309 tests** at the independent-oracle checkpoint.
The four real-frame runs are now complete; results follow below.

The [experiment runner](preparation_experiment.py) is implemented, and all **13
focused harness tests** pass on Ollie. It runs heavy stages in separate sequential
processes, retains failed-run evidence without a success report, and checks
baseline byte identity plus exact layer-isolation invariants. Its inputs are the
saved source extraction, prepared/composed/output baseline bundles, capture and
visually verified identity, followed by a new private output directory:

```sh
systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  env OPENBLAS_NUM_THREADS=1 python3 tools/yblod/reference/preparation_experiment.py \
  /path/to/extraction /path/to/baseline-prepared /path/to/baseline-composed \
  /path/to/baseline-output /path/to/capture.rgb /path/to/identity.json \
  /path/to/NEW-private-run --expected-visible-frame 1943
```

The whole process tree inherits the external hard cap. Do not launch parallel
heavy runs. Keep raw stage bundles private; only `experiment.json` contains the
aggregate results for publication. The identity must describe the actual visible
frame, not a frame guessed from a seek response or driver timestamp.

## Frame-1943 results

The [completed aggregate report](results/preparation-experiment-1943.json)
records all four cases, source/capture identity, operation statistics, code/runtime
pins and exact stage-isolation checks. The regenerated baseline matches every
saved prepared and composer stage, and all **24,883,200 packed-output bytes**,
including inactive borders. Its variant-minus-baseline scores are all zero.

| Case | I mean absolute error | P mean absolute error | T mean absolute error | T even-minus-odd signed-error gap |
| --- | ---: | ---: | ---: | ---: |
| linear / linear | 9.780931 | 4.971984 | 5.603209 | 8.892060 |
| cubic BL / linear EL | 9.780161 | 4.968690 | 5.603787 | 8.892092 |
| linear BL / cubic EL | 9.773123 | 4.980743 | 5.617457 | 8.891921 |
| cubic / cubic | 9.772358 | 4.977403 | 5.618027 | 8.891963 |

All figures are transport-code differences, not perceived/display colour errors.
The T row-gap range across these policies is only **0.000171 codes** after
rounding. These two native phase-conversion kernels do **not** resolve the
observed alternating-row difference in this matched frame. Small mixed movements
in average error do not justify a filter change; no production default changed.
All cubic variants slightly worsen T's average error here; BL-only and both also
increase its maximum absolute error from81 to98 codes.
This does not rule out other coordinates, filters or earlier processing stages.

The factorial controls passed: BL-only changes retain identical EL inputs and
residual stages; EL-only changes retain identical BL inputs, guide and mapped
stages. Every case retains identical luma inputs and reconstructed Y. The both-
changed case retains BL-only mapped stages and EL-only residual stages. Final
transport differences are not assumed to add through nonlinear conversion.

The [resource record](results/preparation-experiment-1943-resources.json) records
**199.34 seconds**, **289,404 KiB** peak process/child RSS, no swapping and exit0
under the 512 MiB hard cap. These are offline diagnostic costs, not playback
measurements. Saved captures remain GUI-plane-disabled with unverified DMA
synchronization; this experiment does not remove those limitations.

Next derive a signed-residual scaling experiment that preserves the physical
sample grid. Compare scaling encoded EL before residual decoding with scaling
decoded signed corrections, keeping their mathematical differences separate from
filter rounding and bounds. A zero metadata threshold does not by itself make
the residual decoder globally linear. Do not implement this as a naive reorder
of the existing unsigned/clamped scaler.

For frame 1943, the imported EL metadata is offset512, slope2048, threshold0,
maximum1048576, denominator23 and EL depth10. The existing integer residual
decoder reduces to `N(s)=16*(s-512)-8*sign(s-512)`, with `N(512)=0` on valid
10-bit inputs; its maximum bound is inactive there. Using the current chroma
filter's 3/4–1/4 weights, encoded `[511,519]` scales exactly to513 and decodes to8.
Decoding first gives `[-8,104]`, which scales exactly to20. This counterexample
contains no rounding or clipping. It establishes a mathematical ordering
difference, not that this neighborhood explains the measured SK4 row pattern.

A residual-space variant also changes working precision: rounding residual
units is finer than rounding encoded EL units in affine regions. The next
experiment must label and isolate that contribution, retain signed values,
record neutral-value crossings and overshoots, and keep coordinates fixed.
Such a CPU diagnostic does not abandon hardware enlargement; a signed-residual
Quick Sync/AMD backend would need a separately validated representation and
transfer/precision/filter contract.

Final regression coverage is **322 reference tests plus 8 accuracy-tool tests**,
all passing on Ollie under the hard cap with swap disabled.
