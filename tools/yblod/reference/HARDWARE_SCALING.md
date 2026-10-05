# Standalone VA-API scaler probe

Implemented source, not a completed hardware measurement. VM execution is
currently blocked on confirming its authorized SSH route. No device permissions,
Kodi configuration, display mode, or playback pipeline have been changed.

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

VPP requests identical BT2020 standards, full code range and left chroma
(`VERTICAL_CENTER | HORIZONTAL_LEFT`, value6) on both sides. These are a declared
code-preserving transport convention, **not the colour meaning of enhancement
data**. Intel's reviewed [driver source](https://github.com/intel/media-driver/blob/master/media_driver/linux/common/vp/ddi/media_libva_vp.c)
can infer colour standards from dimensions when given `None`; we deliberately
avoid that hidden resize-time conversion request. Identity tests must still
verify actual preservation.

The probe queries format/dimension/colour capabilities and records API status,
image layouts, raw capability flags and submitted requests. Scaling/interpolation
flags are encoded selectors, not independent Boolean capabilities; accepted
submission does not prove the named algorithm or dedicated engine was used.
The invocation JSON explicitly keeps `hardware_engine_verified:false`.
Copy-mode colour/chroma request fields are null because they were not submitted.

## Test order

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

Record executable/source hashes, device/driver/kernel, exact commands, input and
output hashes, invocation JSON/API logs and checker results. A GPU download test
is not a steady-state playback benchmark. The offline exact-fraction oracle is
deliberately slow; production-size evaluation needs a separately validated,
memory-bounded comparator, not millions of scalar fractions in a playback path.

P010 cannot represent Annex-B unsigned16 overshoot above1023. Preserve expected
values and report the divergence; it is not evidence of a licensed Dolby clamp
and is not an accepted composer input. Do not introduce RGB conversion to work
around unsupported same-format processing.

## Verified versus pending

- Standalone probe builds cleanly against the target SDK.
- **359 reference tests**, including11 vector/scoring tests and6 compiled CLI
  guard tests, pass on Ollie with no skips under512MiB/no-job-swap constraints.
- Compiled guards test invalid arguments, copy-resize requests, unknown modes,
  bad input sizes and low bits **before any GPU open**. They are not GPU tests.
- The previous8 accuracy tests passed at the preceding checkpoint.
- VM authentication, actual copy/VPP results, larger/production-size comparison
  and engine/performance measurement remain pending. No SK4-match improvement
  or Intel/AMD execution result is claimed.

Compiled guard coverage can be enabled after building:

```sh
YBLOD_VAAPI_PROBE_BINARY=/absolute/path/vaapi_scaler_probe \
  python3 -m unittest discover -s tools/yblod/reference -p 'test_*.py'
```

Without that environment variable, the six compiled tests explicitly skip;
the synthetic Python tests remain runnable from the public source.
