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

Per-layer controls are implemented, and all **20 preparation tests** pass on
Ollie under the 512 MiB hard cap with swap disabled. The four real-frame runs
and independently derived geometry tests are the next checkpoint; no numerical
filter result is asserted here yet.
