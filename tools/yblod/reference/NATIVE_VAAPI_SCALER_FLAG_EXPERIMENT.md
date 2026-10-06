# VA_PROC_PIPELINE_FAST comparison — 2026-10-06

Decision: keep the current flag setting. Disabling it did not show a useful
performance benefit or change the measured engine route in this standalone test.
Kodi and the production scaler implementation were not modified.

## Real-size results

Intel Tiger Lake / iHD 26.3.5; P010 1920x1080 to 3840x2160. A is flag on;
B is flag off. Execution order A1, B1, B2, A2. Each number is the median of
three batches of 64 resident-input submit-and-finish operations.

| Test pair | Flag on (ms/operation) | Flag off (ms/operation) |
| --- | ---: | ---: |
| First pair | 4.284 | 4.323 |
| Reverse-order pair | 4.206 | 4.263 |

All four runs produced the same full 99,532,800-byte synthetic output SHA-256:
`be1861484fbf42a77909ddc2c6caa33fe3673cb1a3bdd33ec1fd67ecc9ccce22`.
This covers constant, ramp, checker and impulse patterns, not just output prefixes.
All whole-code and constant-preservation checks passed; cleanup completed.

The explicit probe DRM client's counters showed video-enhance busy time and
zero render/video busy time in every full-size batch, for both flag values.
This does not identify SFC specifically or prove the route for decoded surfaces
inside Kodi. It contradicts the proposed *runtime* render-route change for this
particular allocation and operation, not the existence of the driver flag logic.

The preliminary 32x32 to 64x64 pair was 0.078 ms on / 0.108 ms off, with equal
output and render-engine activity for both. Small-size overhead is not a playback
performance prediction.

## Method and limitations

The diagnostic C probe uses the unchanged production VA-API scaler helper;
bilinear filtering, BT.2020 full range and chroma locations are held constant.
Only pipeline_fast changes. There are nine untimed ramp executions (one
correctness operation plus eight warmups). Upload/readback and file writing are
outside timed batches. Timing is synchronous helper wall time, not an exclusive
GPU kernel timer or a full playback measurement. Counter snapshot spans are
slightly wider than timing spans; counters are cumulative, one-client scoped and
not frequency normalized. No utilization percentages are inferred.

Each run used a separate systemd scope: MemoryMax=512M, MemorySwapMax=0,
CPUQuota=100%, RuntimeMaxSec=60. All memory events and CPU throttling counters
were zero, swap remained zero; final scope peaks were approximately 190–200 MiB.
Software hashes and Kodi service start ticks matched before/after each run.
This memory cap applies to the diagnostic, not Kodi playback.

Probe compilation used the LibreELEC SDK, -O2, -fno-lto, -Wall -Wextra -Werror
-Wconversion -Wshadow, and libva-drm/libva. The build container was limited to
512 MiB, no additional swap, one CPU and no network.
Binary SHA-256: `98c28481d4e5d2e793bc05458d28e5d06ab11aed085f4f0cdb8fdaaa5991830a`.

The published runner records this exact test deployment, including its fixed
binary location/hash. Adapt those to a new build; do not treat it as a portable
installer. Probe usage: `probe /dev/dri/renderD128 0|1 32|1920 32|1080 NEW_OUTPUT`;
allowed geometries are 32x32 or 1920x1080. Output must not already exist.
Raw per-batch records accompany this report. All inputs were generated patterns;
no movie frames or Dolby metadata are published. This is output equivalence
between flag settings, not a Dolby reference-accuracy qualification.
