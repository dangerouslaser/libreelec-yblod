# Standalone VA-API scaler probe

The first synthetic hardware measurement is complete on the LibreELEC VM.
See [INTEL_SCALING_RESULTS.md](INTEL_SCALING_RESULTS.md) for results and limits.
The [full-size follow-up](INTEL_LARGE_SCALING_RESULTS.md) measures different
engine-class routing and colour-position responses at1920x1080→3840x2160.
The [mode/route follow-up](INTEL_MODE_ROUTE_RESULTS.md) measures default versus
fast/HQ and the separately advertised pipeline hint, without changing playback.
No device permissions, Kodi configuration, display mode, or playback pipeline
have been changed. Normal SSH from the workstation works; the earlier explicit
Petunia-key selection incorrectly excluded the working authentication route.

## Build

`vaapi_scaler_probe.c` is a one-shot C program using libva/libva-drm. On a Linux
development machine with matching headers/libraries:

```sh
cc -std=gnu11 -O2 -Wall -Wextra -Werror \
  tools/yblod/reference/vaapi_scaler_probe.c \
  $(pkg-config --cflags --libs libva libva-drm) -o vaapi_scaler_probe
```

It was compiled on Ollie using the existing LibreELEC SDK: GCC16.2.0,
libva2.24.1/API1.24, target x86_64-libreelec-linux-gnu. The container had no
network, a read-only SDK/source, one CPU, a512MiB hard limit and no container
swap. Compilation passes `-Wall -Wextra -Werror`. The executable requires
GLIBC2.34 or newer and the target's libva/libva-drm/libdrm; inspect dependencies
against the actual VM before invoking it. No runtime libraries are replaced.

## What is actually submitted

Arguments are `DEVICE INPUT OUTPUT IN_W IN_H OUT_W OUT_H MODE`.
VPP modes optionally accept `--input-chroma left|top-left` and
`--output-chroma left|top-left` independently, in either order. Omitted sides
retain `left` (value6); `top-left` is value5. Invalid/duplicate options are
rejected before device access. Copy mode rejects these declarations because
it does not submit a colour-processing request.
VPP also accepts `--pipeline default|fast`, independently of the quality mode.
This requests pipeline flag0 or `VA_PROC_PIPELINE_FAST` (2). The latter must
be advertised by `VAProcPipelineCaps.pipeline_flags`; otherwise the probe
fails without substituting another route. It is a per-job API optimization
hint, not a portable force-render promise. Copy rejects explicit pipeline
declarations. Invocation JSON records actual `pipeline_flags` and
`pipeline_caps_flags`, both null for copy. Default behaviour remains unchanged.
Only even dimensions2..4096 and one exact tightly packed P010 input are accepted.
The output path must be new. Modes:

- `copy`: upload/synchronize/download the input surface. No VPP submission.
- `default`, `fast`, `hq`, `bilinear`, `nearest`: submit an actual VPP job,
  including when dimensions are unchanged. There is no FFmpeg passthrough.

The program creates private P010 surfaces; it never uses Kodi/display surfaces.
Image copies use queried pitches/offsets with bounds, endian and overlap checks.
Only active bytes are exported, with no padded rows. Output is synchronized
before readback; unexpected low-six-bit data is retained for diagnosis, not
coerced into10bit codes. The Python checkers reject it as an unsupported contract.

By default VPP requests identical BT2020 standards, full code range and left chroma
(`VERTICAL_CENTER | HORIZONTAL_LEFT`, value6) on both sides. These are a declared
code-preserving transport convention, **not the colour meaning of enhancement
data**. Intel's reviewed [driver source](https://github.com/intel/media-driver/blob/master/media_driver/linux/common/vp/ddi/media_libva_vp.c)
can infer colour standards from dimensions when given `None`; we deliberately
avoid that hidden resize-time conversion request. Identity tests must still
verify actual preservation.

The probe creates the default VideoProc configuration, then queries settable
P010 surface support. Its generic configuration RTFormat mask is not a decoder
bit-depth list and must not falsely reject supported P010 processing. Colour
capability queries use returned pointers: Intel can replace caller buffers with
driver-owned static lists. Optional unreported pipeline format lists remain
NULL/0; surface attributes and actual explicit P010 processing remain required.
The probe queries format/dimension/colour capabilities and records API status,
image layouts, raw capability flags and submitted requests. Scaling/interpolation
flags are encoded selectors, not independent Boolean capabilities; accepted
submission does not prove the named algorithm or dedicated engine was used.
The invocation JSON explicitly keeps `hardware_engine_verified:false`.
Copy-mode colour/chroma request fields are null because they were not submitted.

The instrumented probe optionally reads its own Linux DRM fdinfo counters
immediately before VPP, after explicit output synchronization, and after image
download. It records raw render/copy/video/video-enhance client nanoseconds
and separate VPP/readback interval deltas. Upload is already synchronized before
the first snapshot. Unknown/missing/malformed counters stay null; deltas require
matching client/device identities and nondecreasing counters. Duplicate fields,
bad units, signed/overflowing values and truncated snapshots are rejected.
These counters exclude Kodi's separate client. They show engine-class activity,
not the SFC sub-block, filter identity, total GPU memory or playback latency.
Zero short-interval activity is not proof that an engine can never be used.
Copy mode has no VPP snapshots; its interval deltas remain null.

## Independent colour-position matrix

```sh
python3 tools/yblod/reference/hardware_chroma_siting_check.py \
  /path/to/vaapi_scaler_probe /path/to/fresh-siting-results --repeats 2
```

This synthetic-only runner tests all four input/output left/top-left pairs.
Copies and all native-size checks precede enlargement. Same-grid1:1 identity,
constant/channel-tag preservation, stable repeats, strict P010 packing and
unchanged luma are gates. Cross-grid1:1 identity is reported, not required:
that declaration can intentionally request colour resampling. The checker
records actual invocation metadata, binary/source/input/output/log hashes,
per-parity differences and independent affine-reference results. No fitted
offset or picture-derived correction is applied. See the results document
for the measured input/output asymmetry and why no setting is adopted as a fix.

## Test order

### Full-size, row-streamed controls

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 hardware_scaling_large.py run /path/to/vaapi_scaler_probe \
  /path/to/fresh-large-results --width 1920 --height 1080 --repeats 2
```

The full-size runner uses ten synthetic patterns: distinct channel constants,
a horizontal slope8 negative control, and vertical slopes±1/2/4/8. Each ramp
has a centred128-native-sample affine band and constant continuation, remaining
within0..1023. A16-output-sample margin inside that band excludes filter support
crossing its ends. Only that interior is compared to rounded Annex-B first
moments; band boundaries are not silently scored as affine. Every downloaded
word is still checked for exact size and zero unused P010 low bits.

Inputs, hashes and validation are streamed in row-sized buffers, rather than
full-resolution lists or Fraction arrays. Ten copies and40 actual native-size
VPP checks finish before80 enlargement jobs (four declarations, ten patterns,
two repeats). Identical output hashes allow score reuse, not pixel fitting.
The independent scalar oracle validates both axes and all signed slopes in
unit tests, including per-pass half-ties toward positive infinity.
Small slopes can conceal a position difference through rounding; they cannot
establish phase agreement by themselves. Successful completion means the
measurement/gates finished, not that hardware matched the reference.

Fresh destinations are mandatory. At production dimensions retained synthetic
downloads occupy roughly2.4GB; these are generated patterns, not media frames.
Resource fields describe Python process-lifetime RSS and diagnostic elapsed
time only, not GPU allocation or steady-state playback performance.

### Signed-ramp, base-value and quality-mode controls

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 hardware_scaling_controls.py /path/to/vaapi_scaler_probe \
  /path/to/fresh-controls --width 1920 --height 1080 --repeats 2
```

This follow-up fixes left→left siting and compares default/fast/HQ requests.
Its96-native-sample bands stay128..888 at slope8, with declared base offsets
0/+1/+2. That keeps the patterns away from endpoint clipping. Cases comprise
horizontal slopes±8, vertical slopes±2/±8 at each base, and distinct constants.
Nineteen copies and57 native-size quality-mode identity checks must pass before
114 enlargements; every scaled case is repeated. Mode hash equality is measured,
not required. Errors are reported against independently validated, separately
rounded Annex-B affine predictions without changing any output pixel.

Whole-frame and interior base-offset comparisons measure whether adding+1/+2
to the input adds exactly that value to the output. Differences use signed
native10bit codes, not packed-byte arithmetic. They are diagnostics, not a fitted
brightness correction or acceptance criterion for Dolby geometry. Passing this
covariance check does not imply that the scaler matches the reference.
Scans and comparison pairs are cached only by full case/scale/output hashes,
never by a lower error score. Row-streaming keeps working memory bounded; retained
generated outputs occupy about3.4GB at production dimensions. No media is used.

### Per-job pipeline-hint comparison

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 hardware_pipeline_route_check.py /path/to/vaapi_scaler_probe \
  /path/to/fresh-route-results --width 1920 --height 1080 --repeats 2
```

This isolates the advertised pipeline hint from the scaling-quality selector.
Quality stays default, siting stays left→left, and the seven safe-band inputs
are the signed horizontal/vertical controls plus distinct constants at base0.
Seven copies and14 native-size checks precede28 enlargements with two repeats.
Unsupported hints, mismatched metadata or identity failures retain failure
evidence without fallback. Hash differences between routes are diagnostic,
not a lower-error selection rule. Own-client engine counters must establish
the observed route response; successful submission alone does not.
No Kodi/global driver/display setting changes. About0.9GB of generated outputs
is retained at production dimensions, with row-bounded validation.

### General small-pattern corpus

Generate configurable vectors on a CPU host without NumPy:

```sh
python3 tools/yblod/reference/hardware_scaling_vectors.py \
  target/new-hardware-vectors --width 64 --height 64
```

The14 patterns cover native endpoints/neutral values, distinct Cb/Cr tags,
single-code steps, bounded ramps, impulses, alternating rows/columns, steps,
overshoot and asymmetric edges. These are scaler-boundary inputs **after**
the native phase adapter, not raw decoder frames or movie/capture material.

For every pattern, using fresh result paths:

1. Run `copy` at64x64 and require byte-exact native-code identity.
2. Run actual `default` VPP at64x64 and separately require identity.
3. Run64x64→128x128 for each requested scaling mode. Unsupported requests retain
   failure evidence; do not silently substitute another mode or mark them passed.
4. Repeat outputs and require stable hashes before interpreting filter differences.

Example single invocation, on a GPU-accessible account:

```sh
./vaapi_scaler_probe /dev/dri/renderD128 \
  /path/to/vectors/channel-tags-input.p010 \
  /path/to/new-results/channel-tags-copy.p010 64 64 64 64 copy
```

`hardware_scaling_vectors.check_identity(planes, downloaded_bytes)` requires
strict packing and reports exact/native-code differences. `score_scaled(planes,
downloaded_bytes)` regenerates independent Annex-B expectations for2x output
and records aggregate, row/column parity, interior/border and overshoot metrics.
It never shifts/fits output or changes golden values. The explicit margin is8
output samples per side in each component; an empty interior is null, not a pass.
Larger ramps are bounded integer staircases, not exact affine coordinate oracles.
The earlier tiny affine tests in `test_scaling_probe.py` retain that separate role.

`hardware_scaling_run.py` automates these stages, validates the canonical bundle
and code pins, and refuses scaling after an identity failure. All subprocesses
are sequential with bounded timeouts; failure retains evidence, not a completed
report. Example on the GPU-accessible system:

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 hardware_scaling_run.py ./vaapi_scaler_probe \
  /path/to/vectors /path/to/NEW-results --modes default fast hq --repeats 2
```

`hardware_phase_check.py` separately tests exact ascending/descending ramps,
using copy and submitted-default identity gates before repeated enlargement.
It predicts affine responses independently of filter tap arrays. It reports
even/odd error sets and output step sizes with a conservative16-output-sample
interior margin. A sign reversal under a reversed ramp distinguishes a sampling-
moment effect from a fixed additive code bias. It never adjusts pixels.

Record executable/source hashes, device/driver/kernel, exact commands, input and
output hashes, invocation JSON/API logs and checker results. A GPU download test
is not a steady-state playback benchmark. The offline exact-fraction oracle is
deliberately slow; production-size evaluation needs a separately validated,
memory-bounded comparator, not millions of scalar fractions in a playback path.

P010 cannot represent Annex-B unsigned16 overshoot above1023. Preserve expected
values and report the divergence; it is not evidence of a licensed Dolby clamp
and is not an accepted composer input. Do not introduce RGB conversion to work
around unsupported same-format processing.

## Production-format constant observation

The probe additionally accepts `--output-format p010|y416` and `--range
full|reduced` (both input and output). Defaults remain P010/full. Output chroma
also accepts `unspecified`; input does not. Copy cannot convert or declare a
range. Requested formats must be advertised; no substitute conversion is used.

`hardware_y416_check.py` first runs24 exact P010 copy/native constant gates,
then requests48 repeated same-size P010420→Y416444 conversions with full and
reduced range. This is conversion observation, **not conversion identity or
spatial-phase acceptance**. It preserves every raw little-endian16-bit word,
reports raw word positions and channel-order/scale hypotheses, alpha separately,
and lower4/6-bit histograms. No bit masking, fitted correction or clamp is used.

```sh
python3 hardware_y416_check.py ./vaapi_scaler_probe NEW-DIRECTORY \
  --width 64 --height 64 --repeats 2
```

The source playback bridge requests Y416/YUV444_12, matching BT2020/reduced range,
input LEFT and output unspecified. Its downstream normalized sampling preserves
fractional native-code precision; the12-bit allocation request alone does not
prove the actual raw storage precision. See `INTEL_Y416_RESULTS.md` for the
initial capability-gated result. No loaded-playback-binary equivalence is claimed.

## Verified versus pending

- Standalone probe builds cleanly against the target SDK.
- **423 reference tests**, including vector/scoring, runner failure gates,
  affine/siting/large/mode/route/format controls,12 host-only DRM parser fixtures and14 compiled CLI guards,
  pass on Ollie with no skips under
  512 MiB/no-job-swap constraints. The8 accuracy tests also pass.
- Compiled guards test invalid arguments, copy-resize requests, unknown modes,
  bad input sizes and low bits **before any GPU open**. They are not GPU tests.
- The64x64→128x128 Intel run, ascending/descending affine controls and independent
  input/output siting matrix are complete.
- Full-size slope controls and per-client engine-class accounting are complete.
- Full-size signed-ramp/base/quality and per-job pipeline-hint controls are complete.
- Production Y416/reduced-range conversion, edge/impulse characterization, specific SFC routing,
  playback performance and AMD measurements remain pending. No SK4-match
  improvement or production acceptance is claimed.

Compiled guard coverage can be enabled after building:

```sh
YBLOD_VAAPI_PROBE_BINARY=/absolute/path/vaapi_scaler_probe \
  python3 -m unittest discover -s tools/yblod/reference -p 'test_*.py'
```

Without that environment variable, the fourteen compiled tests explicitly skip;
the synthetic Python tests remain runnable from the public source.
