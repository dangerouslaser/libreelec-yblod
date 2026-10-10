# LibreELEC YBLOD

An unofficial LibreELEC build with TV-led Dolby Vision for compatible Intel HDMI systems.
YBLOD is not affiliated with or certified by LibreELEC, Kodi, Dolby or Intel.
Please report build-specific problems here rather than to those upstream projects.

## YBLOD 0.2 release candidate

This branch prepares 0.2 with the native playback engine and an updated LibreELEC
base. Final packaged-image checks are in progress; this is not an announcement
that 0.2 has been published. See the [cumulative release notes](docs/RELEASE-0.2.md)
and [available releases](https://github.com/dangerouslaser/libreelec-yblod/releases).

## What changed

- A standalone C/OpenCL engine reconstructs Dolby Vision pictures and packs them
  with frame-matched metadata for TV-led output. Kodi remains the player.
- Decoded surfaces stay on the GPU. Reconstruction uses planar intermediate
  buffers and avoids an unnecessary movie colour-conversion round trip.
- Unchanged GUI graphics reuse cached work. The engine skips its full-screen
  pixel scan when Kodi has not redrawn the GUI and avoids unnecessary reads for
  transparent pixels.
- Movie-only packing can run ahead into the other display buffer. Asynchronous
  overlay packing remains disabled because testing found worse frame delivery.
- Faster live-TV startup avoids duplicate MPEG-TS opens, uses decoded frame-rate
  information, coordinates display changes, and reduces audio startup buffering.
- Playback and menu fixes cover polynomial FEL reconstruction, stale HDR
  signalling, distorted menus after stopping, controls over letterbox bars, and
  Home-screen visibility while a movie plays in the background.

The old **Quick Sync scaling** and **Match Dolby hardware levels** settings have
been removed and their legacy behaviours forced off. Hardware video decoding
remains enabled. The old 0.1 GPU-load and hardware-comparison figures do not
describe this engine.

## Playback pipeline

```text
File -> Kodi / FFmpeg: decode, pair layers and metadata
     -> Intel hardware decoder surfaces
     -> Native C/OpenCL engine: source-picture reconstruction
     -> Planar picture + matching frame metadata
     -> GUI/subtitle composition when needed + Dolby Vision tunnel packing
     -> Patched Intel display driver -> HDMI -> TV display mapping
```

Profile 7 FEL uses the enhancement layer to rebuild the source picture.
Single-layer content skips that branch. CM4 metadata transport is distinct from
display mapping: the TV performs display management in TV-led mode.

The [engine source](native-dv/README.md), [Kodi adapter](native-dv/integration/README.md)
and [implementation references](native-dv/SOURCES.md) are public. The build retains
components from the existing Kodi/libplacebo display and menu integration; the
new engine does not remove every libplacebo dependency.

## Hardware and limitations

This remains an experimental Intel-focused Dolby Vision implementation.
A compatible Intel GPU/HDMI route and a TV supporting Standard TV-led Dolby Vision
are required. AVR and adapter compatibility matters too.

Selected P7 FEL and single-layer scenes have been tested on the N150 and Intel
VM/container setups. Results are specific to the recorded device and workload;
they are not Dolby conformance certification or a guarantee for every file.

- N150 4K59.94 playback can still drop frames with controls open.
- AMD Dolby Vision signalling and AMD OpenCL integration are not included.
  Unsupported P5 playback can have incorrect colours; this is not valid HDR10
  or SDR conversion. The native engine does not add a general DV-to-HDR10 fallback.
- Retired Dolby Vision profiles are unsupported; profile 20 remains deferred.
- Some overlay and screenshot formats remain unsupported; see the
  [adapter limitations](native-dv/integration/README.md#qualification-boundaries).
- GUI pixel caching uses about 158 MiB of additional GPU-accessible memory at 4K.
- First playback can be slower while GPU shaders compile.
- Short test results do not establish long-run stability, physical lip-sync or
  correct appearance on every display and skin.

Measured comparisons and their scope are in [GUI caching](docs/GUI-CACHE-20261010.txt),
[movie-only asynchronous packing](docs/ASYNC-PACK-20261010.txt) and
[GUI revision reuse](docs/GUI-REVISION-20261010.txt). Processing/wait timings are
not end-to-end playback latency and must not be equated to GPU usage percentages.

## QMS and Dolby Vision menus

YBLOD retains QMS refresh switching and optional Dolby Vision menus.
QMS requires a compatible end-to-end HDMI path; ordinary VRR support alone does
not establish QMS support. HDR/SDR colour-mode changes can still cause a blackout.

Kodi's refresh-rate selection uses Settings > System > Display > Whitelist.
The kernel option `i915.qms=0` disables the QMS extension for troubleshooting.

Player > Videos > Dolby Vision retains the menu controls:

- **Dolby Vision for the menu** keeps the menu in Dolby Vision at a 3840x2160 desktop.
- **Menu brightness, saturation, gamma and wide colour** control the standalone
  menu appearance, not the film's colour processing.

## Install and build

Back up your configuration before updating. Download an update `.tar` from
[Releases](https://github.com/dangerouslaser/libreelec-yblod/releases), copy it to
`/storage/.update/`, and reboot. Fresh installations use the `.img.gz`.
Use the checksums and validation notes attached to the specific release.

The YBLOD update channel is separate from official LibreELEC builds. Add-ons
continue to use the configured Kodi/LibreELEC repositories.

`tools/yblod/build.sh <version>` builds in the LibreELEC Docker environment with
a memory cap. Source versions and patches live in the repository at the release
commit. See [branches and updates](docs/yblod/BRANCHES.md).

## Credits and licences

YBLOD builds on LibreELEC, Kodi, FFmpeg, Intel's graphics/media stack, libplacebo,
and CroqueMr's Intel Dolby Vision integration. The native engine's references
include ETSI GS CCM 001 and quietvoid's dovi_tool; see
[native engine source notices](native-dv/SOURCES.md) and [licences](native-dv/LICENSE).
Existing integration notices remain in [docs/intel-dv](docs/intel-dv) and
[licenses](licenses).

Dolby, Dolby Vision and the double-D symbol are trademarks of Dolby Laboratories.
LibreELEC is a trademark of Team LibreELEC. This project is independent.
