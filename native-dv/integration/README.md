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

The patch passes both `git apply --check` and GNU `patch --dry-run --fuzz=0`
against the prepared YBLOD source. Those checks do not establish compilation,
playback, menu correctness or QMS/VRR behavior. The resynced base image and
this adapter require separate build and device qualification.

The unchanged standalone source passes all three Release-mode CPU contract
tests with GCC 14.2 and CMake 4.4.4: specialization admission, geometry and
output-slot ownership. These are not GPU or Kodi playback tests.

The patch is deliberately outside the automatically applied patch directory.
The normal image build does **not yet select or enable the native engine**.
This is inspectable integration source, not a ready-to-install release.

## Explicit development build

1. Prepare the Kodi revision above with this branch's normal patches.
2. Apply `kodi-adapter.patch` to that prepared source.
3. Build the GBM/GLES target with `ENABLE_DVBRIDGE=ON`, using YBLOD's matching
   FFmpeg and libplacebo headers and libraries.
4. Build/install `native-dv` and its OpenCL loader, Intel runtime and compiler
   dependencies from the accompanying package recipes. Matching raw-metadata
   FFmpeg headers are required; stock headers are not interchangeable.
5. Use `runtime.env` as an explicit test configuration, adjusting paths if
   installation is not under `/usr`. Create its writable cache directory.
   Use Kodi resources from the same build as its executable.

The runtime configuration is not installed automatically. Legacy
`DV_PRIVATE_*` names and the library SONAME are retained for ABI compatibility.
Readback, half-resolution GUI and rejected GUI-tile experiments are disabled.

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
