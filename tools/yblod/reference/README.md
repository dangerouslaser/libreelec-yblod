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

[NLQ_STAGE.md](NLQ_STAGE.md) documents the extracted reusable integer enhancement
correction component: validated immutable configuration, explicit metadata cap
before signed flooring, and lazy sample/row processing. It does not choose how
fractional scaler samples become integer inputs or alter current playback.

[COMPOSITION_STAGE.md](COMPOSITION_STAGE.md) connects that component to signed
addition, output rounding and final bounds, with strict paired-stream length
checks and an explicit base-only path. Synthetic bundle tests match the old
reference's Y/Cb/Cr output; base mapping still comes from that reference.

[BASE_MAPPING_STAGE.md](BASE_MAPPING_STAGE.md) and
[STREAMING_COMPOSER.md](STREAMING_COMPOSER.md) document the independently
implemented mapper and assembled chunked prepared-frame runner. All twelve
saved arithmetic stages match the unchanged reference in synthetic differential
tests. Frame-manifest validation is still explicitly shared with the reference;
decoding, spatial preparation, colour conversion and playback remain separate.

[STREAMING_FULL_HD_RESULTS.md](STREAMING_FULL_HD_RESULTS.md) records exact
1920x1080 synthetic equality, measured process memory, and compatibility tests
with the existing diagnostic colour helpers. `make_streaming_demo.py` generates
that larger fixture without copyrighted inputs.

[COLOUR_STAGE.md](COLOUR_STAGE.md) documents the independent scalar colour
component with caller-supplied source/target coordinates and an explicit PQ
domain policy. Its tests cover independent high-precision answers and a bridge
from the new composer through separately expanded synthetic component planes.
No chroma filter, display adaptation or production colour policy is selected.

[COLOUR_FRAME.md](COLOUR_FRAME.md) documents the row-bounded diagnostic output
runner and an end-to-end synthetic CLI workflow. Configuration is explicitly
hash-bound to the composer result. `colour_metadata.py` verifies real settings
against saved extracted-RPU evidence; caller-declared settings retain their
explicit limitation. Output bytes are unembedded diagnostics, not playable
Dolby Vision HDMI.

[NATIVE_PIPELINE.md](NATIVE_PIPELINE.md) describes the C playback direction and
the remaining hardware precision/grid boundary. The tested C foundations are
documented in [NATIVE_COMPOSER.md](NATIVE_COMPOSER.md) and
[NATIVE_COLOUR.md](NATIVE_COLOUR.md); Python remains the reference/test harness.
[REAL_FRAME_VALIDATION.md](REAL_FRAME_VALIDATION.md) and
[NATIVE_COLOUR_RESULTS.md](NATIVE_COLOUR_RESULTS.md) record byte-exact frame-2296
equivalence and bounded offline resource measurements. These rewrites do not
yet reduce the substantial saved SK4 colour differences or replace Kodi.

[NATIVE_BUILD.md](NATIVE_BUILD.md) documents the Python-free C library and
LibreELEC build/run checks. [NATIVE_KERNEL_RESULTS.md](NATIVE_KERNEL_RESULTS.md)
records direct C kernel measurements, not playback FPS.
[NATIVE_INTEGRATION_CONTRACT.md](NATIVE_INTEGRATION_CONTRACT.md) describes the
standalone C frame adapter: copied configuration, explicit whole-code versus raw
diagnostic routes, frame/count checks and arithmetic-only completion.
[NATIVE_INTEGRATION_FRAME.md](NATIVE_INTEGRATION_FRAME.md) records the bounded
full-frame adapter check; it does not select fractional enhancement handling or
establish real-time playback. [NATIVE_METADATA_PROBE.md](NATIVE_METADATA_PROBE.md)
records synthetic tests of the existing TV-led serializer, with reproducible
public output replay clearly separated from fresh C execution.
[NATIVE_METADATA_FRAGMENT_PROBE.md](NATIVE_METADATA_FRAGMENT_PROBE.md) extends
that check to multi-packet messages, exact 119/120-byte boundaries and oversized
message rejection, using synthetic outputs from the actual LibreELEC SDK/VM.
[LIBDOVI_INGESTION_AUDIT.md](LIBDOVI_INGESTION_AUDIT.md) reviews dovi_tool's
C-compatible metadata library as an independent ingestion check, including its
frame-history and ABI limits. The existing extraction workflow is unchanged.
[NATIVE_GPU_CAPS.md](NATIVE_GPU_CAPS.md) and
[NATIVE_GPU_GUARD.md](NATIVE_GPU_GUARD.md) establish device capability and
conservative arithmetic-width gates, not a working GPU playback engine.
[INTEL_Y416_NEUTRAL_RESULTS.md](INTEL_Y416_NEUTRAL_RESULTS.md) records measured
fractional near-neutral values without choosing a reconstruction policy.

[NATIVE_GPU_PROBE.md](NATIVE_GPU_PROBE.md) records isolated GPU
execution checks: the latest 31 supported polynomial/MMR/NLQ/composition cases
matched every tested C stage exactly. One oversized case was explicitly rejected. This is
not a Kodi backend, playback benchmark or improved SK4 colour match.

[NATIVE_GPU_FRAME_PROBE.md](NATIVE_GPU_FRAME_PROBE.md) records 49,152 exact
real prepared-frame sampled stage comparisons, not full-frame GPU correctness.
[EL_OPERATION_ORDER.md](EL_OPERATION_ORDER.md) and
[ANNEX_B_RESAMPLER_VECTORS.md](ANNEX_B_RESAMPLER_VECTORS.md) separate the public
reference operation order from its informative example filter.
[EL_SHADER_SAMPLING_AUDIT.md](EL_SHADER_SAMPLING_AUDIT.md) traces the inspected
playback source's conditional half-pixel sampling and normalization; it is not
confirmation of a loaded Kodi build or licensed-player behaviour.
[SAMPLING_CONTRACT.md](SAMPLING_CONTRACT.md) defines a standalone exact C
sampling diagnostic that preserves fractional words and keeps coordinate,
filter and normalization declarations separate; it selects no playback policy.
[DISPLAY_MANAGEMENT_GAPS.md](DISPLAY_MANAGEMENT_GAPS.md) distinguishes source
colour conversion, the existing TV-led metadata/transport hand-off, and a
separate future player-led display-mapping contract.

[NATIVE_TEXTURE_PROBE.md](NATIVE_TEXTURE_PROBE.md) records the small synthetic
GPU sampling check: sampled/intermediate values matched its declared float
model, with separately recorded final-correction differences. It is not a
Kodi import or licensed fractional-input rule.

Latest complete published-candidate Ollie check: **812 reference tests plus 8 accuracy tests**, no
skips, under a 512 MiB per-job memory limit with job swap disabled. Older counts
below describe their historical checkpoints, not current suite coverage.

`known_answers.py` supplies a separate arithmetic oracle using exact fractions
and 60-digit decimal calculations, rather than the renderer's own functions.
`test_known_answers.py` checks fixed synthetic answers, PQ anchors, matrix order,
all 1024 input codes of a nonlinear mapping, enhancement signs and saturation,
and exact rounding boundaries. None of these expected answers comes from SK4
pixels. The project transport conventions are distinguished from published
arithmetic; passing these tests is not Dolby conformance certification.

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

[SCALING.md](SCALING.md) records the public-spec/alignment audit, independent
Annex-B oracle and synthetic P010 probes. These check scaling without fitting
movie captures; they do not yet invoke Intel/AMD hardware.

[HARDWARE_SCALING.md](HARDWARE_SCALING.md) documents the now-built standalone
VA-API probe and larger synthetic vectors. The first VM measurements are in
[INTEL_SCALING_RESULTS.md](INTEL_SCALING_RESULTS.md); these are synthetic results,
not production acceptance or a resolved SK4 comparison.

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

`--pts` is in the container stream's time base, not seconds. The extractor accepts
single-track Profile 7 streams with unique integer presentation timestamps,
including reordered pictures. It distinguishes coded packet order, source
presentation order and the local decoder output order; none is automatically an
on-screen frame number. Reordered streams currently require a paired BL/EL/RPU
for every coded picture. Missing/duplicate timing, unsupported metadata reuse
and ambiguous associations are rejected. This is not a general HEVC extractor.

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
  and decode a bounded window. When starting at an open CRA, remove only complete
  initial leading RASL pictures that cannot be decoded without earlier references.
  Preserve RADL pictures and later groups. A target needing earlier references
  forces an earlier access point or fails closed; decoder errors are never ignored.
- Record every retained/discarded packet, source and rewritten byte offsets, and
  hashes. A discarded packet may carry redundant parameter sets only when their
  bytes exactly match the latest retained definitions; other decoder-state changes
  fail closed. Verification reconstructs the window from this source mapping.
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

Use short lossless clips and an external memory limit. `--max-window-frames`
bounds the decode window (1024 coded pictures by default, 256 in movie tests),
not all memory or disk use: packet tables and RPU export still scale with clip
duration. On Ollie, heavy jobs run sequentially under `MemoryMax=512M` and
`MemorySwapMax=0`; that limit is not automatically installed by these tools.
Check remuxed timestamps: one tested FFmpeg remux lost or duplicated leading
timestamps despite exiting successfully. The tested `mkvmerge` clips preserve
the timing required by our association checks.

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

Automated coverage includes independent known-answer vectors, extraction,
preparation, reconstruction, transport packing and diagnostic reports,
plus the eight existing accuracy-tool tests. The real-frame inspector also
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

Five **explicit hypotheses**, not automatically selected corrections:

- `direct`: source -> common linear LMS -> target, without a display-RGB bound.
- `rgb-bound-diagnostic`: additionally converts common LMS into BT.2020 RGB,
  limits each component to 0..1 and converts back before target conversion.
  Its HPE-to-RGB matrix is documented from the existing renderer. This isolates
  an existing behaviour for investigation; it is not an independently validated
  Dolby requirement or a claim of clean-room derivation of every constant.
- `rgb-lower-bound-diagnostic`: only replaces negative intermediate RGB values
  with zero; does not impose an upper RGB limit.
- `rgb-upper-bound-diagnostic`: only limits intermediate RGB values above one;
  does not impose a lower RGB limit at that stage.
- `source-pq-bound-diagnostic`: limits source nonlinear components to 0..1
  **before PQ decoding**, without the subsequent RGB bound. This tests a different
  location, not a second adjustment added to the RGB-bound case.

All policies still apply the documented PQ-domain and final transport bounds;
`direct` means no intermediate RGB bound, not absence of every limit. Linear
one here is the 10,000-nit PQ normalization, **not** the file's source/mastering
peak. Scene brightness metadata does not specify the RGB cube used by these
diagnostics. Frame 2296's source nonlinear maximum is 1.3982; extending PQ gives
an intermediate RGB maximum of 75.8962. This is an extrapolated calculation,
not evidence of authored 759,000-nit picture content. The source matrix followed
by HPE-to-RGB is nearly identity for this frame, so different bounding locations
may look similar. See the [ITU PQ definition](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2100-2-201807-S%21%21PDF-E.pdf)
and [Dolby's description of scene measurements](https://professional.dolby.com/en-gb/content-creation/dolby-vision-for-content-creators/).

All policies save float32 intermediate files (calculations use float64), 12-bit IPT
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

Preparation now processes FIR temporaries in 32-row chunks; saved plane hashes
and every operation statistic matched the existing frame-2296 preparation
exactly. Measured peak RSS for that preparation is 290,292 KiB. Extraction now
streams compressed Annex-B units instead of copying entire streams into memory;
this retains exact NAL bytes and passes delimiter-boundary tests. Other extractor
steps, external tools and packet lists are not generally bounded for full movies:
keep the hard cap and current short-file scope. A pre-streaming extraction was
stopped by its isolated memory cap, not allowed to exhaust the host. Its retry
completed under the same 512 MiB cap; no swap was permitted.

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

### Multi-frame reports

`summarize_cases.py` takes matched direct/bounded output directories, each with
`output.json` and `sk4.json`. It validates frame identity, reconstruction/RPU,
reference-capture association, rectangle, colour-coordinate and processing
settings, comparison report links, and streamed hashes of compared tunnel files.
It reports every frame/channel separately with metric changes and flags every
metric increase; it does not average frames into a single reassuring score or
declare a production pass. Other saved float stages and original captures are
not re-read by this summary; the individual comparator checks the capture.

```sh
python3 tools/yblod/reference/summarize_cases.py \
  --case target/reference-frame-461-output-direct target/reference-frame-461-output-bound \
  --case target/reference-frame-2296-output-direct target/reference-frame-2296-output-bound \
  --output target/sk4-case-summary.json
```

`compare_regions.py DIRECT BOUND CAPTURE --output NEW.json` additionally checks
errors separately where the saved pre-bound RGB has negative components, values
above one, both, or neither. Only the active picture is scored; P/T both use the
classification at their co-sited even-x pixel. Labels use float32 saved stages,
so values at a rounding boundary may classify differently from the float64
calculation. Empty groups have zero samples/null scores. The tool checks the
RGB-stage and original-capture hashes and streams 64 rows at a time. This stops
an improvement in one group from concealing a regression in another.

### Four matched SK4 frames, five controlled variants

The existing visible-counter-verified SK4 captures at frames 461, 1406, 1960 and
2296 were reused; no device playback changes or AM9 capture were needed. Native
layers/RPU were independently extracted for each new frame, with exact packet
association and matching one-/four-thread decodes. All use linear preparation
and the same active rectangle as above. See the committed
[four-frame report](results/sk4-numbered-four-frames.json) and per-region reports
[461](results/sk4-regions-461.json), [1406](results/sk4-regions-1406.json),
[1960](results/sk4-regions-1960.json), [2296](results/sk4-regions-2296.json).
The [complete five-policy report](results/sk4-numbered-five-policies.json)
preserves all 20 runs' metrics, deltas, verified provenance, and packed-output
byte-identity flags. Reproduce it with `summarize_policies.py`, supplying repeated
`--case DIRECT RGB_BOUND RGB_LOWER RGB_UPPER SOURCE_PQ_BOUND` groups in that fixed
order and `--output NEW.json`. It applies the same matched-pair checks to every
control and makes no automatic policy selection.

Mean absolute I/P/T differences, in 12-bit transport codes:

| Frame | Direct | Later RGB bound | Earlier source-PQ bound |
| --- | --- | --- | --- |
| 461 | 4.8645 / 5.1382 / 5.5003 | identical | identical |
| 1406 | 2.8688 / 4.8060 / 5.0347 | 2.8440 / 4.8056 / 5.0363 | 2.8427 / 4.8059 / 5.0348 |
| 1960 | 13.2181 / 18.6671 / 9.3146 | 13.2219 / 18.6695 / 9.3203 | identical to direct |
| 2296 | 72.3907 / 157.3744 / 40.0069 | 3.2148 / 5.2896 / 4.9335 | 3.1761 / 5.1998 / 4.9082 |

Interpretation, including results that **do not** support a universal RGB clamp:

- All five packed outputs are byte-identical on frame 461.
- Frame 1406 has 4,087 pixels with both negative and above-one intermediate RGB.
  The later bound reduces their mean I error from 41.8960 to 2.4952, while the
  whole-frame maximum I error falls from 114 to 28. Small colour regressions
  remain in some groups. Earlier-PQ and upper-only RGB outputs are byte-identical
  on this frame; the data cannot distinguish their location here.
- Frame 1960 has 367,713 negative-only pixels and no above-one pixels. Limiting
  those negatives slightly worsens all three mean errors in that group (I
  22.5235 -> 22.5880, P 18.3184 -> 18.3591, T 17.9721 -> 18.0674).
  Earlier-PQ and upper-only RGB variants are byte-identical to direct. Its much
  larger remaining overall mismatch is **not solved** by any limit tested here.
- Frame 2296's lower-only RGB variant remains far from SK4: mean errors
  72.3978 / 157.3468 / 39.9916. Upper-only RGB gives 3.0873 / 6.0165 / 4.8973;
  limiting the high side explains the major improvement. Earlier source-PQ
  limiting is slightly closer than the combined later bound in all three means,
  but the variants trade places across other metrics/channels: no universal
  winner is declared. In the 833,648 mixed-extreme pixels, the combined later
  bound reduces mean errors from 511.9038 / 1127.0788 / 264.6042 to
  3.1287 / 6.0935 / 6.0334.
- Regions inside the tested RGB range retain exactly the same error metrics in
  all four direct-versus-combined-bound comparisons. This is a metrics statement,
  not an independent byte-identity test for those masked regions.

All four frames have **the same source colour matrices and offsets** and come
from one synthetic test file. These are useful diagnostic cases, not ordinary
movie coverage, a certification result, or proof of where SK4 limits values.
The next experiment should use different source matrices and more scenes, and
isolate the remaining reconstruction/chroma differences without fitting offsets.
No production playback change is justified by this checkpoint alone.

All heavy jobs ran sequentially with `MemoryMax=512M` and `MemorySwapMax=0`.
The 20 output conversions/comparisons completed with peak process RSS 116,480
KiB and no swaps; the regional/report batch peaked at 58,548 KiB. Earlier
extraction/reconstruction stages used more of the same capped budget. Saved
float intermediates for the full sweep occupy about 10 GiB under ignored
`target/`; only source and numerical reports are public. These are offline
measurements, not evidence of playback performance.

## Independent checks and movie extraction checkpoint — 2026-10-04

At this checkpoint, the suite passed **166 reference tests plus 8 existing
accuracy-tool tests** on Ollie. This includes the independent arithmetic vectors above and new
diagnostic/extraction safeguards reviewed by separate agents. Tests passing does
not mean the hardware discrepancy is solved.

See [frame 1960's investigation](FRAME1960.md) for the remaining mismatch. Its
alternating-row colour difference provides a concrete sampling-position lead;
the backwards-conversion experiment is explicitly limited and does not locate
a faulty stage by itself. No fitted correction was added.

[Movie extraction results](results/movie-extractions.json) cover one frame each
from short lossless **1917** and **Saving Private Ryan** clips, at container PTS
208 in time base 1/1000. In both clips, the selected coded packet is index 3 but
its presentation rank and global RPU index are 5. The complete clips' compressed
packet hashes, sizes and PTS/DTS match the corresponding original packets.
Each selected BL/EL frame is byte-identical between independent one- and
four-thread decoder runs, and its metadata matches the exact source packet.
Both offline reconstructions pass saved-stage addition and rounding checks.
Repeating numbered frame 2296 with the new extractor preserves the original
BL/EL pixels and parsed RPU JSON byte-for-byte.

These movies have different reconstruction and scene instructions, but their
source linear colour matrices match the numbered test. They therefore do not
yet supply the desired real-world matrix diversity. They also have **no matched
SK4 capture in this checkpoint**; source extraction verification is not hardware
frame association, and no movie/SK4 accuracy score is claimed.

The successful movie extractions peaked below 222,000 KiB process RSS;
preparation used about 290,000 KiB. The longer numbered-frame regression peaked
at 512,192 KiB under the 512 MiB hard cap. All heavy jobs were sequential, with
no swaps or OOM failures. The extraction cap is deliberately retained; packet
table/probe overhead still needs attention before long movies are suitable inputs.
Nothing was installed on the playback VM or changed in the production renderer.

To reproduce the movie workflow with your own clip and unused output paths:

```sh
# Run each heavyweight command separately inside your memory-limited scope.
python3 tools/yblod/reference/extract_frame.py "$MOVIE_CLIP" target/movie-native \
  --pts 208 --max-window-frames 256 --expected-sha256 "$MOVIE_SHA256" \
  --dovi-tool target/reference-tools/dovi_tool-2.3.4/dovi_tool
python3 tools/yblod/reference/import_rpu.py target/movie-native
python3 tools/yblod/reference/verify_extraction.py target/movie-native
python3 tools/yblod/reference/prepare_frame.py target/movie-native target/movie-prepared --phase-filter linear
python3 tools/yblod/reference/reference.py target/movie-prepared/frame.json target/movie-composed
python3 tools/yblod/reference/inspect_composition.py target/movie-composed --output target/movie-inspection.json
```

PTS 208 identifies the tested clips, not an arbitrary movie. Set the source,
checksum and timestamp appropriately. This remains an offline reference, not a
replacement real-time player. Intel Quick Sync and supported AMD media scaling
remain explicit production requirements.

## Final colour sampling isolated — 2026-10-04

[The sampling investigation](SAMPLING.md) now has independently calculated
constant/ramp/impulse tests and a strip-based comparison harness. It reproduces
all four saved direct outputs byte-for-byte, then changes only final vertical
colour interpolation. The experiment reports correctly positioned linear/cubic
filters separately from deliberately wrong-position controls.

At this checkpoint, **220 reference tests plus 8 existing accuracy-tool tests**
passed on Ollie. All 16 frame/variant comparisons completed under the
512 MiB cap, with peak process RSS 96,216 KiB and no swap or OOM failures.

The tested alternatives do not explain frame 1960's main discrepancy. Its
smooth-area differences and alternating-row pattern remain. The same row
pattern is present in the other saved captures, so common capture/packing
assumptions also need verification. No filter, colour offset or deployed
playback setting was changed. See the linked report for per-frame numbers,
limits, independent tests and memory-capped reproduction commands.

## Transport bits audited — 2026-10-05

[The transport-precision audit](TRANSPORT_PRECISION.md) independently checks
literal packed bytes and all 4096 component codes, then examines the four saved
SK4 comparisons without modifying their pixels. Almost all of the T-channel
alternating-row **mean error gap** is in the upper-byte contribution, not the
fine-bit contribution. The row pattern also survives an even/odd colour-column
split. This is a location in the stored numbers, not proof of which processing
stage or capture block caused the difference.

The SK4's current device tree identifies S7D. Read-only driver-state inspection
and source review narrow the applicable capture paths; they do not prove the
configuration during the original captures. No new captures, hardware setting
changes, fitted corrections or playback changes were made in this checkpoint.

Current coverage is **246 reference tests plus 8 existing accuracy-tool tests**,
all passing on Ollie. The four audits ran sequentially under the 512 MiB cap,
peaked at 48,232 KiB process RSS, and completed without swapping or OOM failures.

## Paused-picture capture repeatability checkpoint

The repeat-capture tools and protocol are now available in
[CAPTURE_REPEAT.md](CAPTURE_REPEAT.md). Three freshly started capture cycles of
visibly identified frame 1960 produced six byte-identical physical reads, and
the independent analyzer found no picture or metadata differences. All repeated
metadata copies validate. See
[the aggregate report](results/repeat-comparison-1960-osd.json).

The first run includes Kodi's pause overlay, so it is a repeatability diagnostic,
not a clean colour reference. A second, visually verified overlay-free run shows
**frame 1943**, captured with only the GUI framebuffer plane temporarily disabled.
All six reads are again byte-identical, with valid matching metadata; see
[the second report](results/repeat-comparison-1943-gui-disabled.json).
The menu plane was restored and playback stopped after capture.

Driver dumps were unavailable and DMA synchronization remains unverified;
matching reads cannot exclude stale cached data or a systematic capture error.
No renderer correction follows from these results. Compare the second run only
with a source-identified frame-1943 reconstruction, not with frame 1960.

That [matched reconstruction case](results/frame1943-gui-disabled-case.json) is
now complete. Its [row/bit audit](results/transport-precision-1943-gui-disabled.json)
retains a T-channel even-minus-odd signed-error gap of **8.892060 codes**, mostly
in the upper-eight-bit contribution. Thus the row-dependent difference is still
observed with no visible pause overlay and stable reads. Its processing/capture
cause remains unresolved; no fitted offsets have been applied. Current coverage
at that checkpoint was **293 reference tests plus 8 accuracy-tool tests**.

## Native chroma-preparation checkpoint

The [four-case experiment](PREPARATION_EXPERIMENT.md) changes the native phase
conversion filter independently for BL and EL. Its regenerated baseline matches
all saved prepared/composer stages and every packed-output byte. Exact factorial
checks confirm that each variant leaves its untouched layer's stages identical.

The [completed report](results/preparation-experiment-1943.json) shows that the
T row gap remains **8.891921–8.892092 codes** across all four policies; these
tested filter choices do not resolve it. Average errors move slightly in mixed
directions, so no production filter/default changed. This does not exclude other
geometry, reconstruction or capture causes. Runtime was 199.34 seconds, with
289,404 KiB peak process/child RSS and no swapping under the 512 MiB hard cap.
Current coverage is **322 reference tests plus 8 accuracy-tool tests**, passing
on Ollie. The TV/SK4 were not used during this offline experiment.

## Next milestone

1. Isolate enhancement-layer enlargement versus signed residual decoding order
   on the matched, overlay-free frame-1943 case, retaining the explicit GUI-plane
   and unverified-DMA limitations. Derive a signed, coordinate-preserving scaler
   and separate ordering effects from working-precision changes before running
   alternatives. The native-phase and final-vertical filter choices tested so far
   do not resolve the row pattern; no fitted correction is justified.
   Compare earlier-PQ and later-RGB bounds on additional matched SK4 material
   with different source matrices, including ordinary movie scenes. Reordered
   movie extraction is now supported within the restrictions above; source-frame
   verification does not establish the identity of a separate hardware capture.
   Establish that association before reporting movie/SK4 pixel scores. Isolate
   remaining differences without fitting offsets. No AM9 recapture is needed.
2. Add independent dynamic-metadata serialization/embedding before claiming
   complete standalone HDMI output; preserve trim/active-area instructions.
3. Connect the saved EL-stage comparison boundary to the existing Intel path;
   measure format/precision and filter differences before choosing production
   processing order. Probe AMD capabilities on an actual target before promising
   a corresponding backend.

Passing synthetic arithmetic tests does not establish real-world Dolby accuracy,
prove which current path is correct, or justify replacing the deployed renderer.
