# Production-size Intel scaling controls

Measured2026-10-05 on the same LibreELEC VM/Intel8086:9a49/iHD26.3.5
environment as [the small-pattern tests](INTEL_SCALING_RESULTS.md).
No Kodi, display, device-permission or playback settings changed. The SK4 and
TV were not used. This is a synthetic scaler-boundary test, not a movie render
or Dolby conformance claim.

## Reproducible evidence

- [130-job full-size report](results/intel-large-scaling-v8.json).
- [102-job instrumented small-pattern repeat](results/intel-chroma-siting-v8.json).
- Probe binary SHA256
  `52e649a4bd3e22a97900d35be2214015a1a638f4af74a89da3b881ae767efac5`.
- Probe C source SHA256
  `0401c31b94c3b4f3b8c87e1e5904cabfef401e1d6ad28bf135ca5cfa1ef90bcb`.
- Pure DRM parser header SHA256
  `14e689d9c38088e8694f3f9df3b7b246d5e920e6e93c8851c1b2199739c8befa`.

Reports pin runner/dependencies/binary/input/output bytes, exact commands,
invocation declarations and stdout/stderr log hashes. Generated synthetic
downloads/logs remain in the private fresh VM directories. No copyrighted
movie layers or captures are published.

`hardware_scaling_large.py` streams rows instead of constructing full-resolution
Python/Fraction planes. Inputs are1920x1080, outputs3840x2160; all jobs request
default scaling, matching BT2020 standards, full range and horizontal-left
siting. Four input/output vertical siting declarations are measured, not tuned.
Ten patterns include distinct constant channel tags, horizontal slope8 and
ascending/descending vertical slopes1/2/4/8. Affine bands are128 native samples
wide with constant continuation. Only the interior16-output-sample margin is
compared with rounded Annex-B first moments; every frame word is checked for
strict P010 size/low-bit packing. Unit tests cross-check all signed slopes and
both axes against the independent exact, separately rounded two-pass oracle.

## Safety gates and resources

All ten transport copies and all40 submitted native-size jobs are byte-exact,
including cross-grid requests. All native-size gates finish before80 enlarging
jobs. All repeated enlargement hashes are stable; channel constants stay exact
and Y is byte-identical across the four siting requests.

The run takes278.192 seconds including CPU validation, process initialization,
surface upload/download and file I/O. Python process-lifetime peak RSS is26,552
KiB. Jobs run sequentially under a512MiB hard scope cap with job swap disabled.
The scope reaches its cap including charged file cache; sampled `memory.events`
shows reclaim-limit events but zero OOM/OOM-kill events. These are diagnostic
resource observations, not playback latency, sustained throughput or total GPU
allocation. Kodi remains active throughout and after completion.

## Real-size routing is different

The probe reads **its own** DRM client's engine counters before VPP, after
output synchronization, and after download. Deltas require matching device/client
identities and nondecreasing counters. Missing/malformed/decreasing data remain
null, not zero.

| Measured submission group | Jobs | Positive render interval | Positive video-enhance interval |
| --- | --- | --- | --- |
| 64x64 native-size VPP | 48 | 0 | 7 |
| 64x64→128x128 VPP | 48 | 32 | 0 |
| 1920x1080 native-size VPP | 40 | 0 | 40 |
| 1920x1080→3840x2160 VPP | 80 | 0 | 80 |

No copy/video engine-class activity is measured in the full-size VPP intervals.
All four counters are available for these full-size jobs. Small jobs with zero
interval counters are not proof of no possible engine activity; short-job
accounting, optimizations and interval visibility limit that inference.

These observations support different engine-class routing between the tested
small and full-size enlargements. They do **not** identify the SFC sub-block,
guarantee absence of all EU work, explain every filter coefficient, or prove
steady-state playback offload. `hardware_engine_verified:false` stays explicit.
See [kernel accounting semantics](https://github.com/torvalds/linux/blob/master/Documentation/gpu/drm-usage-stats.rst)
and [Intel's distinct processing paths](https://github.com/intel/media-driver/blob/master/docs/media_features.md).

The instrumented small run reproduces every prior output hash and score:
instrumentation changes observability, not the measured image results.

## Full-size image measurements

All values below are 10-bit code differences from the **rounded logical
Annex-B affine reference** inside the specified band, not SK4 differences or
physical layer-registration errors. Ramp Cb and Cr metrics agree.

For vertical slope+8:

| Input→output request | Y even/odd error | Cb/Cr even/odd error |
| --- | --- | --- |
| left→left | 0/−1 | −1/0 |
| left→top-left | 0/−1 | −2/−1 |
| top-left→left | 0/−1 | +2/+2 |
| top-left→top-left | 0/−1 | 0/+1 |

For vertical slope−8:

| Input→output request | Y even/odd error | Cb/Cr even/odd error |
| --- | --- | --- |
| left→left | −1/0 | 0/−1 |
| left→top-left | −1/0 | +1/0 |
| top-left→left | −1/0 | −2/−2 |
| top-left→top-left | −1/0 | −1/−2 |

Changing the input declaration affects full-frame hashes for every vertical
ramp at each fixed output declaration. Changing the output declaration affects
most vertical cases, with slope/rounding-dependent exceptions: slope−1 outputs
are byte-identical under that toggle at either fixed input, and slope+2 is
byte-identical at fixed left input. Constant and horizontal-ramp hashes are
unchanged by siting declarations.
This contrasts with the small-path lack of an observed input-siting response.
Native-size cross-grid identity does not imply that cross-grid enlargement
preserves the same physical picture.

Horizontal slope+8 differs from the reference: Y mean−2.5/max3 codes and
Cb/Cr mean−1.5/max2 codes, independent of the siting pair. Its descending
counterpart has not yet been measured at full size; do not infer a unique
position shift or fixed arithmetic bias from the ascending field alone.

Gentler ramps expose rounding as well as geometry. For left→left, vertical
slope±2 has error−1 on both row parities in all components. Some slope4 colour
responses match exactly, but that does not establish the filter or geometry:
small slopes can conceal differences through rounding. Full parity/absolute
metrics for every slope are retained in the report. No offset is fitted,
reference values changed, or siting declaration selected merely for a lower
mean error.

## Consequence and next discriminating test

Tiny-surface results are not a safe proxy for this production-size hardware
path. We now have a bounded full-size harness and per-client engine evidence;
we do not yet have a hardware result accepted as a replacement for the CPU
baseline or a demonstrated closer SK4 match.

Next repeat mirrored horizontal ramps, integer base-offset controls and the
strongest vertical controls at full size under default/fast/HQ requests.
Record engine classes for each request
instead of assuming a quality label means the same backend. Then use edges/
impulses to distinguish coefficient and boundary behaviour before integrating
a declared hardware scaler contract into reconstruction. Keep range, precision,
physical registration and transfer costs explicit; no picture-fitted correction.
