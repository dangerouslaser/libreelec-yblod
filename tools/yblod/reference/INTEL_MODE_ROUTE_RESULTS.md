# Intel full-size quality, rounding and route controls

Measured2026-10-05 on the LibreELEC VM using private synthetic GPU surfaces.
Same device/driver environment as [the production-size follow-up](INTEL_LARGE_SCALING_RESULTS.md).
No Kodi/global driver/display/device settings changed, and no SK4/TV or movie
frames were used. These are scaler-boundary diagnostics, not a Dolby verdict.

## Signed ramps, integer bases and quality modes

The [190-job report](results/intel-scaling-controls-v8.json) uses V8 probe binary
SHA256 `52e649a4bd3e22a97900d35be2214015a1a638f4af74a89da3b881ae767efac5`.
It pins runner/helper/input/output bytes, commands, invocation declarations and
log hashes. Quality flags are default0, fast256, HQ512; pipeline flags remain
the default zero in this probe version. Range/standards/siting stay FULL,
matching BT2020 and left→left. These are code-transport test conventions.

Inputs are1920x1080 P010; outputs3840x2160 P010. Six ramps (x±8, y±2, y±8)
are tested at integer base offsets0/+1/+2, plus distinct constant channel tags.
The96-native-sample band stays128..888 at slope8, up to890 at offset+2,
avoiding endpoint clipping. Constant continuation surrounds the band; the
16-output-sample interior margin excludes support crossing its ends.
Predictions use independently validated, separately rounded Annex-B first
moments, not unrounded lines or image-fitted coordinates.

All19 copies and57 actual native-size jobs (every quality mode) are byte-exact.
All76 native gates precede114 enlargements, with paired repeat hashes stable.
Constants remain exact under every request.

### Engine-class observations

| Submission | Default | Fast | HQ |
| --- | --- | --- | --- |
| Native-size jobs per mode | 19 video-enhance-positive | 19 video-enhance-positive | 19 video-enhance-positive |
| Enlarging jobs per mode | 38 video-enhance-positive | 38 render-positive | 38 render-positive |

No other engine class has a positive measured VPP interval in these groups.
Counters are from the probe's own client before submission/after synchronization,
not Kodi or system-wide GPU load. They establish observed engine-class activity,
not the SFC sub-block, absence of all EU processing, or sustained playback
offload. `hardware_engine_verified:false` remains explicit.

FAST and HQ are byte-identical to **each other** in all19 scaled cases. Default
matches them only for constant tags; all18 ramp outputs differ. This does not
mean either scaler universally agrees with the reference or a licensed player.

### Direction and rounding measurements

Interior10bit-code errors below use column parity for x ramps, row parity for
y ramps. Cb and Cr ramp metrics agree. All three input base offsets give the
same reference errors.

| Pattern | Default Y even/odd | Default Cb/Cr even/odd | Fast/HQ Y even/odd | Fast/HQ Cb/Cr even/odd |
| --- | --- | --- | --- | --- |
| x+8 | −2/−3 | −2/−1 | 0/0 | 0/0 |
| x−8 | +1/+2 | +1/0 | 0/0 | 0/0 |
| y+2 | −1/−1 | −1/−1 | 0/0 | 0/0 |
| y−2 | −1/−1 | −1/−1 | −1/−1 | −1/0 |
| y+8 | 0/−1 | −1/0 | +2/+2 | +2/0 |
| y−8 | −1/0 | 0/−1 | −2/−2 | −2/0 |

Mirroring horizontal ramps changes default errors directionally, but opposite
directions do not cancel: paired errors sum−1 at each parity. This exposes
rounding/quantization asymmetry as well as a directional sampling response;
it is not a unique recovered filter or a justified fixed brightness correction.

All36 nonzero base-offset comparisons (six ramps, two offsets, three modes)
have **zero whole-frame and interior translation deviations** in Y/Cb/Cr.
Adding+1/+2 to every input code adds exactly+1/+2 to every output code, including
band boundaries. The inputs avoid obvious endpoint clipping. This shows integer
translation preservation for the bounded corpus; it does not eliminate fractional
rounding, establish filter coefficients or prove arbitrary-content precision.
No covariance error is hidden with a fitted gain, offset, shift or clamp.

The run takes536.892 seconds including CPU scans, repeated process initialization,
uploads/downloads and file I/O. Python process-lifetime peak RSS is28,048 KiB.
Jobs are sequential under512MiB/no-job-swap; sampled scope events show zero
OOM/OOM-kills while file-cache reclamation enforces the cap. Kodi remains active.
These are not playback latency or sustained-throughput measurements.

## Separate per-job pipeline hint

The [49-job route report](results/intel-pipeline-route-v9.json) uses V9 binary
SHA256 `99ea83439fb94a9509e5ee459557609942f183d1425c5fa514b3f0f974059206`.
Its C source SHA256 is
`486c24d6a65e173cb6568b0db330109f8a8a133ffc456f649d04d54b257ed98b`;
the unchanged DRM parser header is pinned in prior results.
The only varied request is `pipeline_flags`: zero or `VA_PROC_PIPELINE_FAST`2,
not quality `VA_FILTER_SCALING_FAST`256. Quality remains default, with the same
FULL/BT2020/left→left conventions and seven safe-band base0 inputs.

The driver advertises pipeline capability mask2. All seven copies and14 actual
native-size checks are exact and precede28 enlargements, with paired outputs
stable. Both pipeline requests produce byte-identical images for every pattern,
and both match the preceding V8 default-quality outputs exactly.
All42 submitted VPP intervals show positive video-enhance activity and zero
measured render/video/copy activity. Therefore the advertised and submitted
hint has **no observed image or engine-class response in this experiment**.
It did not realize a force-render comparison. This is not evidence that the
driver universally ignores the hint, and successful submission is not an
engine-selection guarantee. Unsupported hints would fail without fallback.

The run takes79.595 seconds including CPU scans/I/O; Python process-lifetime
peak RSS is25,000 KiB. It runs sequentially after the190-job batch under the
same512MiB/no-job-swap cap. Diagnostic elapsed time is not playback performance.

## Source interpretation and production scope

Intel's reviewed legacy Gen12 source has a branch where FAST means SFC only
when VEBOX is otherwise needed; ordinary scaling can then use composition/render.
That is consistent with measured FAST/render work, but the runtime vendor commit
`3de4708` remains unresolved and no execution trace proves that source branch.
The softlet path has different preference overrides; it must not be treated as
a universal explanation for these jobs. [Legacy branch](https://github.com/intel/media-driver/blob/intel-media-26.3.5/media_driver/agnostic/gen12/vp/hal/vphal_render_vebox_g12_base.cpp#L2712)

The tracked [production offload patch](https://github.com/dangerouslaser/libreelec-yblod/blob/80e412cb68ebc8a3b6a2c5f5200c51c18af5fe34/projects/Generic/patches/kodi/kodi-9999-yblod-01-qsv-offload.patch#L671)
already requests DEFAULT with pipeline flags zero, not the render-associated
FAST/HQ requests above. Its failure path falls back to shaders, without silently
retrying another quality request. This source inspection does not establish
which exact source built the running Kodi binary.

Crucially, the production code requests P010 to Y4164:4:4/12bit surfaces under reduced-range
conventions, with renderer sampling handling; these tests retain P0104:2:0/10bit
under FULL-range conventions. This format/range difference can affect precision
and geometry. Current native-format results cannot certify that production
conversion path, its extra precision, or its final reconstructed output.

The public Annex-B reference is an informative example, not a universal licensed
Dolby scaling mandate. Agreeing with one affine control does not accept a backend.
Physical BL/EL alignment, range, rounding, precision and transfer costs remain
explicit contracts, and no SK4-match improvement has been claimed.

## Next bounded experiment

Test the production format conversion itself: P010→Y416 with the same declared
range, bit-depth, colour and siting conventions as the offload patch. First
establish exact native-code interpretation and endpoint/neutral/tag preservation,
then repeat full-size signed ramps with explicit higher-precision expectations.
Do not drop output precision back to10bit before judging it. Only then compare
edge/impulse responses and feed declared scaler outputs through NLQ/composition
fixtures. No mode change or pixel correction is adopted on these results alone.
