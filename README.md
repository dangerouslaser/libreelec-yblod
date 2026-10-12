# LibreELEC YBLOD

An unofficial LibreELEC build for Intel PCs that sends Dolby Vision to the TV (TV-led
Dolby Vision over HDMI), with Kodi as the player.

YBLOD is not affiliated with or certified by LibreELEC, Kodi, Dolby or Intel. Please report
problems with this build here, not to those projects.

**Download:** [latest release](https://github.com/dangerouslaser/libreelec-yblod/releases/latest).
Each release has its notes, a validation report and checksums.

## Editions

| Edition | Contents |
|---|---|
| Standard | LibreELEC with YBLOD's Dolby Vision playback. |
| LG | The same build, plus the Estuary LG skin (set on a fresh installation), the LG webOS TV Control add-on and the repository that keeps both updated. |

Both editions are built from the same source and released together, each with its own update
channel.

## What it does

- **Dolby Vision to the TV.** YBLOD's engine rebuilds each Dolby Vision picture on the
  Intel GPU and sends it with its frame-matched metadata to the TV, which does the display
  mapping. Decoded frames stay on the GPU, and reconstruction uses exact integer arithmetic,
  so performance work never changes the output.
- **Profiles.** Profile 7 (FEL and MEL) and Profile 8 (tested with 8.1 and 8.4). For FEL, the
  enhancement layer is used to rebuild the full picture.
- **Menus and subtitles in Dolby Vision.** Kodi's controls, menus and subtitles are composited
  into the Dolby Vision picture, including over letterbox bars.
- **Light on the GPU.** Only the active picture area of letterboxed films is processed, and
  unchanged on-screen graphics are not reprocessed.
- **HDR10 conversion.** Dolby Vision can instead be converted to HDR10 output for TVs
  without Dolby Vision.
- **QMS refresh switching** on HDMI paths that support it, for fewer blackouts when the
  refresh rate changes. VRR support alone does not mean QMS support. Disable it with the
  kernel option `i915.qms=0`.
- **Faster live TV startup**, through fewer stream opens, coordinated display changes and
  less audio buffering.

```text
File -> Kodi / FFmpeg (decode on the Intel GPU, pair layers and metadata)
     -> YBLOD engine (OpenCL): rebuild the Dolby Vision picture
     -> menus/subtitles composited, packed for the Dolby Vision HDMI tunnel
     -> patched Intel display driver -> HDMI -> TV display mapping
```

## Settings

**Settings > Player > Dolby Vision:**

- **Dolby Vision output:** TV-led Dolby Vision, conversion to HDR10, or Kodi's standard
  playback. Applies to the next video.
- **Colour upscaling:** Gaussian or Lanczos, for videos shown through the compatibility
  renderer.
- **Enhanced player information:** video, audio, metadata and GPU usage on the player
  information panel (O).
- **Dolby Vision for the menu:** keeps Dolby Vision on while the menu is shown, so Dolby
  Vision videos start without the TV switching picture mode (needs a 3840x2160 desktop),
  with menu brightness, saturation, gamma and wide colour.

With the settings level set to Expert, two more groups appear:

- **Engine:** the native engine itself, processing only the picture area of letterboxed
  films, fast on-screen controls, reusing reshaping tables, reusing unchanged controls and
  the home screen over video, preparing frames ahead, and half-resolution menus (faster
  with controls open, softer menu text). Everything except half-resolution menus is on by
  default and leaves the picture unchanged.
- **Diagnostics:** output verification, a frame timing log and a GPU timing log, for
  troubleshooting.

These settings take precedence over the same switches in `/storage/.config/native-dv.env`.
Other engine switches can still be set there (restart Kodi afterwards); see the
[engine integration notes](yblod-engine/integration/README.md).

## Requirements and limitations

- An Intel GPU with HDMI output, and a TV that supports standard (TV-led) Dolby Vision.
  AVRs and adapters in the HDMI path must pass Dolby Vision through. Most testing is on an
  Intel N150 and an 11th-generation Core (Tiger Lake).
- 4K at 50/60 fps with the playback controls open can drop frames on low-power Intel GPUs
  such as the N150. 24 fps films are not affected.
- Profile 5 is not supported and can show incorrect colours. Retired Dolby Vision profiles
  are not supported. There is no general Dolby Vision to SDR fallback.
- AMD GPUs are not supported.
- The first playback after an update can start more slowly while GPU shaders are compiled.
- Switching between HDR and SDR picture modes can still cause a short blackout.
- Testing covers specific devices, files and TVs. It is not Dolby certification and does
  not guarantee every file, display or skin.

## Installing and updating

Back up your settings first. To update, copy the `.tar` for your edition to
`/storage/.update/` and reboot; for a fresh installation, write the `.img.gz` to a drive. After
that, updates arrive through YBLOD's own update channel in LibreELEC's settings. Add-ons
keep using your configured Kodi repositories.

## Building and contributing

`yblod/tools/build.sh <version>` builds the standard edition in the LibreELEC Docker build
environment; `YBLOD_EDITION=lg yblod/tools/build.sh <version>` builds the LG edition.

YBLOD's own code and docs live in two folders, which keeps it easy to follow upstream
LibreELEC:

- [`yblod-engine/`](yblod-engine/README.md): the Dolby Vision pipeline (engine source,
  tests, its Kodi, FFmpeg, libplacebo and kernel patches, tools and docs).
- [`yblod/`](yblod/README.md): the distribution (other patches, the LG edition, build and
  release tools, release notes).

See [repository layout](yblod/README.md) and [branches, releases and contributing](yblod/docs/BRANCHES.md).

## Credits and licences

YBLOD builds on LibreELEC, Kodi, FFmpeg, Intel's graphics and media stack, libplacebo, and
CroqueMr's Intel Dolby Vision work ([libreelec-x86-DV](https://github.com/CroqueMr/libreelec-x86-DV)).
The engine's references include ETSI GS CCM 001 and quietvoid's dovi_tool; see the
[engine source notices](yblod-engine/SOURCES.md), [engine licence](yblod-engine/LICENSE),
and the [integration notices](yblod-engine/docs/intel-dv) and [licences](yblod-engine/licenses).

Dolby, Dolby Vision and the double-D symbol are trademarks of Dolby Laboratories. LibreELEC
is a trademark of Team LibreELEC. This project is independent.
