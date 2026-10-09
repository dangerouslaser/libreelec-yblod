# Experimental YBLOD Kodi adapter

This patch targets Kodi `63063c8e67b1f162761763c0cbdb1a5dcfc3a47e` after
YBLOD's common and Generic patches on the LibreELEC resync commit
`2efc53dffbdc4b2fb05e1a2e6b74f33b2479c4c5`.

It ports the previously qualified native adapter to YBLOD's own bridge. It
does not require replacing that bridge with the newer CB1 integration.
The standalone reconstruction engine is unchanged from the source published
in `dangerouslaser/intel-dv-libreelec` at
`4e0ffc4c0f4f351f44de9c02a67a39c628558f6e`.

The adapter keeps decoded VAAPI surfaces on the GPU, manages asynchronous
reconstruction and two output buffers, and composes video controls in the
source colour representation. The existing DV menu and legacy QSV VPP paths
are retained. Native movie-overlay processing and GUI reuse exclude the
standalone menu, which keeps its existing packing and appearance controls.

## Current status

The complete Generic image has built and booted on the N150. The installed
engine has passed selected current-profile controls/recovery checks, and initial
GPU timestamp baselines are available in
[QUALIFICATION-20261009.txt](QUALIFICATION-20261009.txt). Early P7 presentation
gaps and remaining accuracy, menu and QMS/VRR gates keep release qualification
open. These results apply to the exact image identified in that report.

The unchanged standalone source passes all three Release-mode CPU contract
tests with GCC 14.2 and CMake 4.4.4: specialization admission, geometry and
output-slot ownership. These are not GPU or Kodi playback tests.

The patch is `projects/Generic/patches/kodi/kodi-9999-yblod-03-native-source.patch`.
Generic builds apply it after the existing YBLOD QSV and menu patches and
install the engine and dependencies through Kodi's package recipe. This is
unqualified integration source, not a ready-to-install release.

## Build and runtime

Use YBLOD's normal Generic x86-64 image build. The package recipes select the
GBM/GLES adapter, matching modified FFmpeg and libplacebo, the native renderer,
the OpenCL loader, and pinned Intel runtime/compiler dependencies. Stock
FFmpeg headers are not interchangeable with the matching metadata extension.

The native package installs `runtime.env` as `/usr/lib/kodi/native-dv.env`
and a Kodi service drop-in. Startup creates the writable cache directory.
Optional `/storage/.config/native-dv.env` entries override the packaged values.
For a legacy-renderer diagnostic, disable `DV_PRIVATE_SOURCE`,
`DV_PRIVATE_OVERLAY` and `DV_PRIVATE_DRAIN_EOF` together, then restart Kodi.
Disabling the source alone leaves native-only composition/drain hooks active.
Use the separate base image for a strict before/after integration comparison.
VAAPI driver selection is left to the system; qualification must verify the
actual Intel driver and OpenCL libraries loaded, not just environment values.

Legacy `DV_PRIVATE_*` names and the library SONAME are retained for ABI
compatibility. Readback, half-resolution GUI and rejected GUI-tile experiments
are disabled. Keep Kodi's resources and executable from the same build.

## Qualification still required

- Current 2D profile playback, cold start, controls, pause/seek and EOF.
- Packed-output accuracy checks and before/after N150 performance measurements.
- P7 FEL/MEL performance and frame/layer ownership across transitions.
- DV menus, their appearance controls, movie/menu handoffs, QMS/VRR and audio.
- Full image packaging and runtime dependency verification.

The route targets 3840x2160 progressive output with admitted source geometry
and metadata. HDR bitmap overlays and native composite screenshots remain
unsupported. Retired profiles are unsupported; profile 20 is deferred.
The existing engine tests are not independent Dolby conformance tests.

`MEASUREMENTS.md` is historical context comparing the prior and newer CB1
adapters. It is **not** a measurement of this YBLOD port.

The new adapter code uses GPL-3.0-or-later; existing Kodi and bridge notices
remain applicable. See the renderer's LICENSE and SOURCES.md.
