# Full-size reversed bands, steps and source-stripe placements

2026-10-05; same Intel8086:9a49/i915, iHD26.3.5(3de4708), LibreELEC VM and
standalone V11 binary as the earlier full-size Y416 run. All tests used
1920x1080 P010 input and native1920x1080/enlarged3840x2160 Y416 readback.
No Kodi, playback, output-mode or display settings changed.

Three sequential batches completed with all repeats stable:

| Corpus | Cases | Exact P010 gates first | Y416 observations | Total invocations |
|---|---:|---:|---:|---:|
| Neutral + descending bands | 7 | 14 | 28 | 42 |
| Neutral + isolated steps | 7 | 14 | 28 | 42 |
| Neutral + stripe placements0/1 | 13 | 26 | 52 | 78 |

Requests stayed DEFAULT, BT2020/REDUCED both sides, LEFT6→unspecified0,
pipeline0 and explicit Y416/YUV444_12. All Y416 jobs were unadvertised output
allocation diagnostics; no replacement format or fallback was used. Each batch
performed a retained-file disk preflight with an additional256MiB reserve. All
raw files remain on the VM; only synthetic aggregate reports are published.

## Descending bands and mirror balance

The96-native-sample descending band is `888−8*k`, k0..95; it is the exact
mirror of the previous `128+8*k` band. Their sum is1016, **not1024**; index48
has descending code504, not512. Inactive components remain512.

Native centre-line ascending/descending sums were exactly1016 throughout.
Enlarged affine interiors retained opposite, symmetric errors against the
predeclared pixel-centred hypothesis: Y±1/2 and Cb/Cr±1/4 code. Whole centre-line
mirror balances were exact except12Y or4chroma samples with a+1/4-code residual,
all outside the32-output-sample-margin affine interior near band boundaries.
These are response/rounding observations, not recovered Dolby geometry or a
calibration offset. No correction was fitted or applied.

Evidence: `results/intel-y416-large-descending-v11.json` and
`results/intel-y416-descending-response-v11.json`. The executed runner source is
preserved at public commit `396bf10252`, SHA256 beginning `57872f`.
After this run, a metadata-only fix derived the centre code correctly for odd
small test fixtures; full-size generated pixels and source declarations are
unchanged. Edge/stripe reports pin the later runner beginning `979fec`, present
in commit `04682fd67e`. Derived metrics were regenerated from untouched aggregate
data with the final stronger source/profile validation, and pin both measurement
reports and scoring source. Do not claim the current runner hash matches the
earlier descending measurement hash.

## Step response

Each step changes only one component512→576 at its native midpoint; no gain or
plateau normalization is used. Native responses were exact0..64 relative to
neutral. Fixed cropped plateau checks had zero error in all cases.

Enlarged full-centre-line response ranges and known-stimulus10–90% widths:

| Driven component/axis | Min/max relative to512 | Width in output samples |
|---|---|---|
| Y horizontal/vertical | −8/72 | 57/35 (≈1.63) |
| Cb/Cr horizontal | −5/69 | 251/85 (≈2.95) |
| Cb/Cr vertical | −10/74 | 251/85 (≈2.95) |

Threshold widths use exact straight-segment interpolation of observed samples,
not identified filter coefficients. Ringing differs by component/axis. These
safe stimuli do not establish nominal-range clipping behavior or a licensed
filter. Reports: `results/intel-y416-large-edges-v11.json` and
`results/intel-y416-large-edge-response-v11.json`.

## Stripe placements and integer translation

Each stripe raises a single native row/column by64 on a512 background. Placement1
is one integer native component sample after placement0. The `phase0/1` names
mean source placement, **not** independently varied fractional scaler phases.

All12 native/enlarged centre-line overlap comparisons translated exactly:
nativeY+1output pixel, nativeC+2; enlargedY+2, enlargedC+4. The stored centre-line
profiles had no nonzero stripe response outside the128-sample scoring crop.
The derived report separately preserves full-profile masses and absolute
centroids, so crop coordinates are not mistaken for full-surface registration.

Enlarged stripe response relative to neutral:

| Driven component/axis | Min/max codes | Signed mass in raw-word units |
|---|---|---:|
| Y horizontal/vertical | −11/59 | 8192 |
| Cb/Cr horizontal | −5/62 | 16384 |
| Cb/Cr vertical | −10/64 | 16384 |

These are stripe (not2D point-impulse) response statistics. Masses or centroids
from these placements are not universal phase/DC conservation, a fitted phase,
or Dolby alignment targets. Reports: `results/intel-y416-large-stripes-v11.json`
and `results/intel-y416-large-stripe-response-v11.json`.

## Invariants, engines and resources

Across all three batches, every non-driven colour channel and alpha matched
its same-size neutral baseline by whole-frame raw-word hashes. Native alpha
remained65535; enlarged alpha65472. Alpha is not treated as a colour sample.

All108 Y416 submissions recorded positive video-enhance intervals and no positive
render/copy/video intervals; this is DRM engine-class evidence, not proof of
SFC specifically or a steady-state performance measurement.

| Batch | Python peakRSS KiB | Runner seconds | Cgroup max events |
|---|---:|---:|---:|
| Descending | 37856 | 36.15 | 842 |
| Edges | 38020 | 32.47 | 910 |
| Stripe placements | 50404 | 61.79 | 2157 |

Each scope was capped at512MiB with job swap disabled; each reached that cap.
All `oom`, `oom_kill`, `oom_group_kill` counters and current swap were0. `max`
events are limit-pressure events, not OOM counts. Python RSS is separate from
cgroup-charged memory, and neither measures all possible GPU allocations.
Runner time includes CPU scanning and retained raw-file I/O, **not playback cost**.

Afterwards Kodi was active, available memory about2.19GiB, and `/storage` had
2.9GiB free (91% used). No files were removed. Further large batches should wait
for an explicitly approved retention/archive plan or sufficient disk space.

## Reproduction

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 hardware_y416_large_detail.py ./vaapi_scaler_probe-v11 NEW-DIRECTORY \
  --corpus descending --repeats 2
# Use a separate new directory for --corpus edges or --corpus stripes.
python3 y416_large_detail_metrics.py DESCENDING-REPORT.json NEW-METRICS.json \
  --ascending-report results/intel-y416-large-v11.json
```

No playback defaults, SK4 comparison or licensed-pipeline accuracy claim changed.
The next arithmetic checkpoint must distinguish the integer reference contract
from a hypothetical fractional-sample extension before accepting an adjustment.
