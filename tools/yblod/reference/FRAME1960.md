# Frame 1960: investigating the remaining difference

The difference is real in the saved output data, but its cause is not yet
established. This investigation does **not** justify a new colour offset,
weakening the enhancement layer, or declaring either renderer correct.

Source: `DV FEL All Layers Test (Woman at 80s).mkv`, visible frame **1960**, source
PTS **81748/1000 seconds**. Its SHA-256 is
`04085d8eae7efe23397c025184e8d72258d80761b671f641a83a8dd7b4ae8c7f`.
The reference is the existing SK4 Pro capture, not a new AM9 capture.

## Direct observations

The [output diagnosis](results/frame1960-diagnosis.json) compares the saved
transport codes without fitting offsets or shifting either picture.

- Differences remain in smooth areas: mean absolute differences are **12.05 I,
  13.56 P, and 8.03 T codes**. This is not only an edge-filter problem.
- One colour channel has a strong alternating-row pattern: mean signed T error
  is **+10.93 on even rows**, **+2.11 on odd rows**. Sampling position or processing
  order is worth investigating, but this pattern does not identify its cause.
- Only **67 of 6,178,560 active pixels** have a source nonlinear colour component
  outside `[0,1]`. The saved source maximum is below 1. The source upper-limit
  experiment therefore cannot explain this frame's discrepancy.
- All three copies of both captured metadata packets are identical and pass
  their checksums. The captured colour-coordinate matrices match our comparison
  coordinates. This validates the decoded data format, not Dolby compliance.

The metadata is **not identical in every field**. L1, L2 and L6 match the source.
The captured L4 values are `[1471,987]`, versus source `[1515,1001]`; captured L5
margins are all zero, versus source `[0,0,275,276]`. Comparisons still use the
source active rectangle `[0,275,3840,1884]`.

[Checking nearby source metadata](results/frame1960-neighbor-metadata.json)
found no matching L4 pair in frames 1958–1963. Thus, the simple suggestion that
the capture carries metadata two frames ahead is not supported by this check.
It does not settle wider timing questions or explain the metadata changes.

## What the inverse experiment tells us—and does not

The [inverse experiment](results/frame1960-inverse.json) mathematically works
backwards through the signalled colour conversions. It samples only even
horizontal positions, where all three captured components refer to the same
picture location; it does not interpolate the captured picture.

These are **inferred source-coordinate values**, not internal SK4 buffers.
All scores use the same **2,363,529 samples**. Another **725,751 samples (23.5%)**
are excluded because at least one required calculation is outside its supported
domain. Captured endpoint codes are also conservatively excluded; there are
none in this particular sampled area. Conclusions do not cover the excluded
samples.

| Comparison, on the shared valid samples | Mean absolute Y difference |
| --- | ---: |
| SK4 inferred values versus our complete reconstruction | 47.78 codes |
| SK4 inferred values versus reconstruction with Y enhancement removed | 111.71 codes |
| Our own packed output worked backwards versus our reconstruction | 5.71 codes |

Keeping the enhancement contribution agrees better in this experiment. This
does not support removing it. It also does not prove that the SK4 applies it
exactly as we do.

The control exposes an important limitation: even our own correctly associated
output does not invert exactly after rounding. Its worst Y difference is
**302.76 codes**. Working backwards can greatly magnify small output changes;
the control is not a rigorous error bound for the SK4. Do not interpret the
larger inferred differences as directly measured reconstruction errors or
visible picture errors.

## Next diagnostic

Investigate vertical colour sampling in the **forward** direction, where these
inverse-conditioning problems do not arise. First use constant-colour, vertical
ramp and single-row impulse inputs with independently calculated expected
positions. Then hold reconstruction, colour matrices, limits and packing fixed
while isolating the final colour enlargement step. Report alternating-row and
smooth-area differences separately across the existing four frames.

This is a stage-localization experiment, not a search for whichever filter wins
one hardware comparison. Broad smooth-area differences must remain visible;
an edge improvement alone cannot close this investigation. A production filter
still needs independently justified geometry and reproducible tests.

## Reproduction and memory

The raw movie, extracted layers and device captures are not distributed here.
The linked reports record their hashes. With the matching local bundles, run
each command separately from the repository root under a **512 MiB hard memory
cap**, with one numerical-library thread. Existing output files are not replaced.

```sh
systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0 -- \
  env OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 tools/yblod/reference/diagnose_frame.py \
  target/sk4-sweep-1960-direct "$SK4_CAPTURE" \
  --report target/frame1960-diagnosis-reproduced.json

systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0 -- \
  env OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 tools/yblod/reference/inverse_stage.py \
  target/sk4-sweep-1960-direct \
  target/reference-frame-1960-composed-linear \
  target/reference-frame-1960-streamed "$SK4_CAPTURE" \
  --report target/frame1960-inverse-reproduced.json
```

Set `SK4_CAPTURE` to the matching `native.rgb` before running. These tools process
32-row strips. The initial inverse run peaked at approximately **120 MB RSS**;
the endpoint-exclusion follow-up preserved the same valid sample count and
scores. Playback was not changed.
