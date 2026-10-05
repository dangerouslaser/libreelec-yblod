# Offline reconstruction reference

This is an independent, deliberately slow Python implementation of the
**prepared-input composition stage**, not a complete Dolby Vision renderer or a
certified reference. It does not depend on Kodi, libplacebo, CroqueMr's shaders,
NumPy, a GPU or a connected TV. Python 3.9+ is required for the core. Preparation
and inspection companions require NumPy (tested with 1.26.4 on Ollie).

The reconstruction core takes one already-decoded, already-aligned pair of 4:2:0
frames plus explicit fixed-point composition parameters. It writes the mapped
base layer, signed enhancement correction, their unrounded sum, and reconstructed
output. It does **not** decode MKV/HEVC, parse an RPU, rescale the enhancement
layer, expand chroma, convert to RGB, pack HDMI output, or perform TV display
mapping. Companion tools extract native layers, import instructions, prepare
and reconstruct a real frame, and now convert/pack offline transport pixels for
comparison with the Ugoos SK4 Pro. This is not yet a complete playback pipeline:
the new packer does not serialize/embed dynamic metadata or signal HDMI mode.

## Public quick start (no build host or video file required)

This branch publishes working experimental source as it develops. Tested
checkpoints are committed and pushed; listed future tasks are not claims of
implemented features. Contributions can start with the synthetic bundle below.

```sh
git clone --depth 1 --branch experiment/dv-reconstruction https://github.com/dangerouslaser/libreelec-yblod.git libreelec-yblod-reconstruction
cd libreelec-yblod-reconstruction
python3 -m venv .venv-dv-reference
.venv-dv-reference/bin/python -m pip install -r tools/yblod/reference/requirements.txt
.venv-dv-reference/bin/python -m unittest discover -s tools/yblod/reference -p 'test_*.py' -v
mkdir -p target
.venv-dv-reference/bin/python tools/yblod/reference/make_demo.py target/demo-input
.venv-dv-reference/bin/python tools/yblod/reference/reference.py target/demo-input/frame.json target/demo-output
.venv-dv-reference/bin/python tools/yblod/reference/inspect_composition.py target/demo-output --output target/demo-inspection.json
```

Use fresh destination paths if repeating the example. No Kodi image build,
Dolby hardware, Ollie access or proprietary movie file is needed for these tests.
For real-frame extraction, additionally provide FFmpeg/ffprobe, the linked
dovi_tool binary, and your own appropriate source file; replace the example
Ollie paths below with local paths and use that source's exact PTS/checksum.
Raw video and capture artifacts are intentionally excluded from Git.

## Run the tests and a synthetic example

From the repository root:

```sh
python3 -m unittest discover -s tools/yblod/reference -p 'test_*.py' -v
python3 tools/yblod/reference/make_demo.py /tmp/yblod-reference-input
python3 tools/yblod/reference/reference.py /tmp/yblod-reference-input/frame.json /tmp/yblod-reference-output
```

Choose unused paths. Neither command overwrites an existing destination.
`make_demo.py` generates a tiny 4-by-2 artificial frame, not movie material or a
real Dolby RPU. Expected reconstructed Y samples are
`0, 4, 2044, 2048, 2052, 4088, 4092, 2050`.

## Arithmetic and evidence

The calculation basis is [ETSI GS CCM 001 V1.1.1 (2017-02)](https://www.etsi.org/deliver/etsi_gs/CCM/001_099/001/01.01.01_60/gs_ccm001v010101p.pdf),
clauses 5.4.2 (piecewise polynomial/MMR base mapping) and 5.4.3 (enhancement
inverse quantization and addition/rounding). This is a public compound-content
specification, not evidence that every current Dolby implementation is identical.
No implementation code was imported from another renderer.

Implementation decisions to keep visible during review:

- Arbitrary-width Python integer accumulators avoid overflow. Floating-point
  coefficients are rejected, rather than silently quantized.
- Internal pivot boundaries select the interval to their right. At/above the
  final pivot, the last interval is used. This explicitly resolves an apparent
  endpoint/index ambiguity in clause 5.4.2.2; it is an interpretation to verify
  against real metadata, not a claim of proven hardware behavior.
- Signed right shifts round toward negative infinity. The correction stays
  signed until addition. Only the documented mapping, correction and final
  reconstruction bounds are applied; there is no intermediate RGB clipping.
- Residuals and sums use signed 32-bit dump storage, not signed 16-bit storage.
  The accepted coefficient envelope can generate corrections outside int16.
- The initial bundle supports only PQ, planar 4:2:0 and declared horizontal-left,
  vertically-centered chroma. Base and enhancement grids must already coincide.
- MMR requires luma at chroma positions. The core requires that plane as an
  explicit input (`mmr_luma`). `prepare_frame.py` now implements the clause
  5.4.2.3.3 operation, with separate rounding at each pass and edge replication.
- Missing required enhancement input is an error, even though a base-only
  recovery could be possible. Base-only reconstruction must be explicitly
  requested with `disable_residual: true`.

The resampling discussion in annex B is informative. Its example filters are
now available as a CPU comparison baseline, not a production requirement. This
does not establish which Quick Sync settings or processing order best matches
the devices.

## Input contract

Use the generated `frame.json` as the executable example of schema
`yblod.composer-frame.v1`. Files must remain inside its directory; relative paths
and symlinks escaping the bundle are rejected. Each layer has three tightly
packed, row-major, little-endian unsigned 16-bit files (`Y`, `Cb`, `Cr`). Samples
are **right-aligned codes**, not P010 words, not normalized floats, not video-range
expanded values. Each chroma plane has width/2 by height/2 samples. EL files must
already have the same dimensions and sample phase as BL files.

The BL, EL and metadata records each carry an identical `frame_id`, integer
`pts`, and `[numerator, denominator]` `time_base`. These assertions catch mixed
bundles; they cannot prove that a decoder/exporter assigned them correctly.
A real input adapter must verify frame association against source timestamps
and the visible counter, and preserve source-file/RPU provenance. Playback wall
clock time alone is insufficient.

The metadata object specifies input depths (8 or 10), output depth (10 or 12),
`coefficient_log2_denom`, and three mappings. Each mapping contains **absolute**
strictly increasing pivots and one segment per interval. Polynomial coefficients
are listed constant-first. MMR uses a fixed-point `constant` and one to three
rows of seven coefficients ordered Y, Cb, Cr, YCb, YCr, CbCr, YCbCr; each row
corresponds to the next order. MMR is chroma-only.

All coefficients are combined signed fixed-point integers, with the common
denominator declared above—not raw fractional fields or decimal approximations.
Enhancement parameters per component are `offset`, `slope`, `threshold` and
`maximum`. Only `nlq_method: "linear_deadzone"` is implemented. `import_rpu.py`
now translates supported dovi_tool 2.3.4 JSON fields into this contract without
floating-point conversion. Unsupported forms, including previous-RPU references,
are rejected rather than guessed. Its output is metadata only, not a ready-to-run
frame manifest.

The required `preparation` text must describe how the layers were aligned/scaled
and how MMR luma was prepared. For actual captures, record decoder/version,
original dimensions, source checksum, frame identification and filter choices;
the generated synthetic fixture is not a template for asserting these facts.

## Output contract

The output directory must not exist. Input validation precedes its creation.
`report.json` is written last; an interrupted run may leave incomplete stage
files. Only a readable report with `status: "complete"` denotes a completed run.

For each component, files contain:

- `mapped_*.u16le`: mapped base-layer 16-bit codes.
- `residual_*.i32le`: signed correction on the same internal scale.
- `sum_*.i32le`: mapped base plus correction, before output rounding and bounds.
- `reconstructed_*.u16le`: right-aligned output-depth codes, still planar 4:2:0.

The report embeds the input manifest and SHA-256 hashes of the manifest, code,
consumed input planes and output planes, plus stage sample counts and extrema.
Outputs are reproducible and contain no timestamps generated by the program.
They are **not RGB images or native HDMI tunnel samples**. The separate
`output_frame.py` stage below is required before scoring against SK4 captures.

## Native frame extraction

The extractor requires FFmpeg/ffprobe and
[dovi_tool 2.3.4](https://github.com/quietvoid/dovi_tool/releases/tag/2.3.4).
The checked Linux x86_64 release archive has SHA-256
`1844258e13c26607b32224bf1fa82b595d3b35949f5467405fda560daad32b3f`.
It is kept under ignored `target/reference-tools/dovi_tool-2.3.4/` on Ollie,
not installed system-wide or included in the image.

From the worktree root, with an unused output directory:

```sh
python3 tools/yblod/reference/extract_frame.py \
  /home/bryan/Projects/libreelec-yblod/target/dv-fel-numbered-test.mkv \
  target/another-frame-2296-run \
  --pts 95762 \
  --dovi-tool target/reference-tools/dovi_tool-2.3.4/dovi_tool \
  --expected-sha256 04085d8eae7efe23397c025184e8d72258d80761b671f641a83a8dd7b4ae8c7f
python3 tools/yblod/reference/import_rpu.py target/another-frame-2296-run
python3 tools/yblod/reference/verify_extraction.py target/another-frame-2296-run
```

`--pts` is in the container stream's time base, not seconds. The extractor is
currently restricted to single-track Profile 7 with monotonic, non-reordered
container packets. Enhancement decoder reordering is handled through packet
positions. It is not a general extractor for arbitrary HEVC containers.

The checks are deliberately stronger than selecting the same ordinal from two
decoder outputs:

- Locate exactly one original container packet by PTS and preserve its bytes.
- Compare its BL/EL coded slices byte-for-byte with the corresponding demuxed
  stream frames. Track missing EL/RPU entries instead of assuming counts match.
- Compare the packet's RPU payload with the global extraction and independently
  parse both. The preserved `.nal` includes the HEVC header; dovi_tool's `.bin`
  representation omits that header and adds a start code. No conversion mode is
  used and no metadata values are edited.
- Find each layer's own preceding access point, require complete parameter sets,
  and decode a bounded window. EL uses a closed IDR rather than an open CRA to
  avoid multi-slice leading-picture seek issues.
- Match the selected decoded frame back to its encoded packet offset. Strict
  decoding errors abort the run. FFmpeg's packet-boundary zero padding is
  handled separately from the exact full-stream coded-slice comparison.
- Split the resulting native Y/Cb/Cr planes without scaling or range expansion.
  Repeat decoding with one thread instead of four and require identical bytes.

`extraction.json` is written only on successful extraction. `composition.json`
contains normalized instructions and original header flags; full display metadata
remains in `rpu.json`. `verification/verification.json` records the repeat-decode
and integrity checks. Earlier failed attempts have no completed extraction
report and must not be used as input. All movie material stays under ignored
`target/`, separate from source control.

## Verified frame 2296 extraction — 2026-10-04

On Ollie the successful bundle is:
`target/reference-frame-2296-v7/` in the reconstruction worktree.

- Source checksum matches the earlier SK4 comparison file.
- Container PTS is 95762 at time base 1/1000; zero-based source packet and RPU
  ordinal are both 2296. The final `bl-counter.png` was visually checked and
  reads **frame 02296 / sec 95,762**, matching the saved SK4 comparison counter.
  This preview is only an identification aid, not Dolby-rendered output.
- BL: 3840x2160; EL: 1920x1080. Both are native planar 10-bit 4:2:0 and signal
  **top-left chroma**, not the core's left/vertically-centered contract.
  Extraction preserves this discrepancy. Preparation now performs and records
  an explicit conversion instead of relabeling the unmodified samples.
- The native BL/EL SHA-256 values are respectively
  `4b182fdb58314f1fe6aee3dd70d16dbdb59bf36aeff92007d8dc8a3f193225c1` and
  `558ea69a8141f8cb89474745d48183a15251bcd91154b674bc2655250b5fd706`.
- Both strict decodes succeed and reproduce exactly with one and four threads.
  BL decoding starts at source frame 2280; EL starts at its closed access point
  2232. The target's presentation indices within those windows are 16 and 64.
- Parsed instructions identify Profile 7 FEL, 10-bit inputs, 12-bit reconstructed
  output, and 23 fractional coefficient bits. Luma has eight linear pieces;
  both chroma components have third-order MMR. All components have enhancement
  offset 512, slope 2048, threshold 0 and maximum 1048576 (fixed-point integers).
- The full source has 2878 BL pictures but 2876 EL pictures/RPUs; source indices
  2875 and 2876 lack EL/RPU entries. Those omissions are after our target.
- Strict decoding of the initial demuxed BL section reports errors; tolerant
  FFmpeg probing drops 24 pictures. Naively selecting decoded picture 2296 would
  therefore select the wrong source picture. The bounded, packet-verified
  extraction does not use that count. This observation is not a diagnosis of
  whether the original file or a remux/header interaction caused those errors.

The extraction record's `visible_counter_verified` remains false because the
script cannot verify text visually; the manual observation is documented above.
Extraction milestone coverage was 44 unit tests plus real-frame extraction/import
and single-thread repeat-decode checks. This validates extraction, not DV rendering.

## Explicit preparation and first real-frame reconstruction

The preparation adapter creates a new bundle; it never edits native captures.
For top-left chroma it samples at one quarter of a native chroma row farther
down, producing left/vertically-centered chroma. This is done separately at each
layer's native resolution. Two explicit experimental filters are available:
`linear` and `cubic128`. Neither has been established as the right hardware
match. The core's chroma layout contract is unchanged.

EL then uses the literal informative annex B vertical-then-horizontal filters.
Its vertical intermediate is saved. BL luma stays byte-identical; the MMR luma
guide is prepared using the visually checked clause 5.4.2.3.3 equation. All
input/output sample locations, filter coefficients, rounding, bounds, hashes and
intermediate planes are recorded in `frame.json`.

Annex B's written upper bound is 65535. The adapter does not secretly replace it
with 1023: if a prepared EL sample exceeds the declared 10-bit input depth, the
run fails rather than adding an undocumented clamp. That ambiguity does not
arise for the extracted frame 2296. Resolving it for other signals is future work.
The separate experimental chroma-position filter explicitly rounds and bounds
its output to the native input depth; those events are counted in the manifest.

Example (use fresh destination paths):

```sh
python3 tools/yblod/reference/prepare_frame.py target/reference-frame-2296-v7 target/prepared-example --phase-filter linear
python3 tools/yblod/reference/reference.py target/prepared-example/frame.json target/composed-example
python3 tools/yblod/reference/inspect_composition.py target/composed-example --output target/inspection-example.json
```

Repeat with `--phase-filter cubic128` in separate directories to test sensitivity.
Pass `--compare SECOND_RESULT_DIRECTORY` to the inspector for a source-verified
comparison. Results are **reconstructed Y/Cb/Cr codes**, not HDMI output or a
displayed picture. No RGB preview is used to claim Dolby accuracy.

Both real-frame runs completed on Ollie:

- `target/reference-frame-2296-prepared-linear/` and `...-prepared-cubic/`.
- `target/reference-frame-2296-composed-linear/` and `...-composed-cubic/`.
- `target/reference-frame-2296-comparison.json` contains checked addition,
  rounding, bounds and full-plane sensitivity measurements.

Y is identical between the two preparation policies. Cb is 94.1881% identical,
with a mean absolute difference of 0.06435 and maximum difference of 8 codes.
Cr is 96.2684% identical, with mean absolute difference 0.03876 and maximum 6.
These are 12-bit component-code differences across the entire raster, not a
perceptual score or a comparison with the Ugoos captures.

In the linear-policy run, 83,343 of 2,073,600 Cb samples reach the final upper
bound after rounding; the cubic run has 82,696. No Y or Cr samples exceed the
final output bounds. This identifies a concrete reconstruction-stage limit to
investigate. It does **not** show that the older RGB clamp was correct or explain
the old/fast hardware-output discrepancy by itself.

Current automated coverage: 76 reference/extraction/preparation/output tests
plus all eight existing accuracy-tool tests. The real-frame inspector also
verifies every saved component's signed addition and final rounding/bounds.

## Hardware scaling is a production requirement

The CPU filters are test instruments, not the intended playback implementation.
Retaining Intel Quick Sync offload and enabling an AMD hardware-backed option
where supported are explicit design requirements. No AMD backend or new Intel
backend has been implemented in this standalone package yet; the existing
playback path is unchanged.

`el-scaling-job.json` is the saved boundary around the EL scaling stage, including
input/output planes, frame identity, dimensions, depth, layout, sample positions
and hashes. It deliberately excludes RPU processing and layer combination.
This lets a hardware adapter be measured independently of reconstruction.

Production acceptance must include:

- Actual per-device input/output format and video-processing support. Do not
  assume AMD exposes the same combinations or filters as Intel.
- Native sample precision, storage alignment and chroma positions. The current
  CPU baseline uses 10-bit samples in 16-bit containers; do not force a hardware
  path with additional useful precision through a 10-bit round trip just to fit
  this first contract. Extend the reference representation and tests if needed.
- Total playback cost, including conversion passes, surface copies, CPU
  readbacks, render-engine use and video-engine use. The intended playback path
  should retain GPU surfaces, not use these offline disk checkpoints.
- Picture differences on the same input, separately from speed measurements.
  Matching this illustrative filter bit-for-bit is not automatically required;
  any tolerance needs evidence from difficult clips and hardware comparisons.
- Scaling may include chroma processing. A 4:4:4 hardware result is not
  interchangeable with the 4:2:0 reference stage by changing its format label.
- A hardware implementation may combine preparation operations to save work,
  but changes to phase, rounding or operation order must be measured explicitly.

Do not let an unverified software filter choice dictate expensive extra playback
passes or prevent useful hardware offload.

## Offline colour conversion and SK4 comparison

`output_frame.py` consumes a completed reconstruction and its hash-linked native
extraction/RPU. It expands 4:2:0-left chroma with an explicitly experimental
bilinear filter, applies the source metadata's colour matrices and PQ transfer,
and changes coordinates into the existing TV-led transport basis by inverting
the exact target metadata matrices. No source movie, capture, fitted offset,
Kodi or libplacebo renderer is needed by the colour conversion code.

The target matrices are the integers already used by this project's transport
and observed in SK4 metadata; they are not claimed as universal Dolby defaults.
Source/target matrix semantics follow [ETSI CCM001 section 6.2.2](https://www.etsi.org/deliver/etsi_gs/CCM/001_099/001/01.01.01_60/gs_ccm001v010101p.pdf).
PQ negative inputs become zero, above-one inputs remain extended, and a decode
pole/nonfinite value is rejected. Output is rounded using `floor(x*4096+0.5)`
and bounded to 0..4095. Each intermediate records its range and negative/above-one
sample counts; those two counters are domain diagnostics for normalized float
stages, not overflow counts for the integer code/byte stages.

Two **explicit hypotheses**, not automatically selected corrections:

- `direct`: source -> common linear LMS -> target, without a display-RGB bound.
- `rgb-bound-diagnostic`: additionally converts common LMS into BT.2020 RGB,
  limits each component to 0..1 and converts back before target conversion.
  Its HPE-to-RGB matrix is documented from the existing renderer. This isolates
  an existing behaviour for investigation; it is not an independently validated
  Dolby requirement or a claim of clean-room derivation of every constant.

Both save float32 intermediate files (calculations use float64), 12-bit IPT
codes, and top-down RGB8 tunnel pixels. P/T are sampled at the even pixel of
each pair. L5 defines black borders. **No metadata is embedded in this new
output**, so it must not be deployed as a playable DV signal. This checkpoint
implements pixel packing only; standalone metadata serialization is still open.

On Ollie, run one job at a time inside a hard memory cap. These commands require
a functioning user systemd manager with memory-controller support; do not remove
the cap silently if unavailable. Use unused output directories.

```sh
systemd-run --user --scope -p MemoryHigh=384M -p MemoryMax=512M -p MemorySwapMax=0 \
  env OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v \
  python3 tools/yblod/reference/output_frame.py \
  target/reference-frame-2296-composed-linear target/reference-frame-2296-v7 \
  target/reference-frame-2296-output-direct --policy direct

# Repeat sequentially with a new directory and --policy rgb-bound-diagnostic.
systemd-run --user --scope -p MemoryHigh=384M -p MemoryMax=512M -p MemorySwapMax=0 \
  env OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 tools/yblod/reference/compare_output.py \
  target/reference-frame-2296-output-direct /path/to/sk4/native.rgb \
  /path/to/reference.json --report target/reference-frame-2296-output-direct/sk4.json
```

The comparison identity JSON must contain `source_sha256`,
`visible_frame_number` (zero-based source packet index), and `pts_us`. This is a
user-verified association, not a timestamp guessed from driver state. The saved
SK4 capture's driver PTS differs from its visible counter; the latter was
confirmed as 02296/95.762s. The comparator checks source/frame/PTS identity,
capture size, generated-plane hash, two first-copy packet CRCs and exact target
matrix equality. It currently accepts only the observed two-packet layout and
an active rectangle wholly after embedded metadata; it does not yet validate
all three metadata repetitions. Decoding/CRC helpers come from `../accuracy`,
not its colour-transform function. Synthetic tests exercise packing, capture
byte ordering, frame mismatch, corruption, strip seams and round-trip arithmetic.

### Frame 2296 result (2026-10-04)

Only the **Ugoos SK4 Pro** is the current hardware reference. Same source frame,
linear preparation, active rectangle `[0,275,3840,1884]`, no fitted offsets.
Mean absolute differences in 12-bit transport codes:

| Output policy | I | P | T |
| --- | ---: | ---: | ---: |
| Direct | 72.3907 | 157.3744 | 40.0069 |
| RGB-bound diagnostic | 3.2148 | 5.2896 | 4.9335 |

Maximum errors change from 901/2200/631 to 23/51/43. This is strong evidence
that a colour-domain bound explains much of this frame's discrepancy. It is
**not proof** of SK4's internal processing order, the correct rule for all
content, or an acceptable production tolerance. Errors remain; chroma expansion,
fixed-point rounding, source reconstruction, and matrix precision need separate
tests. Do not use these results to undo hardware scaling or add fitted offsets.

Conversion streams 64-row strips: measured peak RSS was 108,988 KiB direct and
115,096 KiB bounded; both completed with zero swaps under the 512 MiB cgroup cap.
Offline elapsed times (3.17/3.46 seconds) are **not playback benchmarks**. Saved
stages occupy about 451/546 MiB per policy; private frame data stays under ignored
`target/`, not in Git. Capture SHA-256:
`afb200d61bb672eef1bbeb6b6363eff562fa6a878da1137810c5b922164f9dd9`.

## Next milestone

1. Test the explicit colour-bound hypothesis on additional matched SK4 frames,
   including ordinary movie scenes and extreme colours. Isolate the remaining
   differences without fitting offsets. No AM9 recapture is currently needed.
2. Add independent dynamic-metadata serialization/embedding before claiming
   complete standalone HDMI output; preserve trim/active-area instructions.
3. Connect the saved EL-stage comparison boundary to the existing Intel path;
   measure format/precision and filter differences before choosing production
   processing order. Probe AMD capabilities on an actual target before promising
   a corresponding backend.

Passing synthetic arithmetic tests does not establish real-world Dolby accuracy,
prove which current path is correct, or justify replacing the deployed renderer.
