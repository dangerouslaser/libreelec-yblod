# LibreELEC YBLOD

An unofficial LibreELEC build for Intel and AMD PCs that plays Dolby Vision in Kodi: sent
to the TV as TV-led Dolby Vision over HDMI, or converted by YBLOD's own engine for TVs and
projectors without it.

YBLOD began as a fork of CroqueMr's Intel Dolby Vision build of LibreELEC, now
[libreelec-CB1](https://github.com/CroqueMr/libreelec-CB1), and still builds on his work;
see [Credits and licences](#credits-and-licences).

YBLOD is not affiliated with or certified by LibreELEC, Kodi, Dolby, Intel or AMD. Please
report problems with this build here, not to those projects.

**Download:** [latest release](https://github.com/dangerouslaser/libreelec-yblod/releases/latest).
Each release has its notes, a validation report and checksums.

## Editions

| Edition | Contents |
|---|---|
| Standard | LibreELEC with YBLOD's Dolby Vision playback and the Estuary YBLOD skin (the default skin; stock Estuary is still included). |
| LG | The same build, plus the LG webOS TV Control add-on and the repository that keeps it and Estuary YBLOD updated. |

Both editions are built from the same source and released together, each with its own update
channel.

## What it does

- **Dolby Vision to the TV.** YBLOD's engine rebuilds each Dolby Vision picture on the
  GPU (Vulkan compute) and sends it with its frame-matched metadata to the TV, which does
  the display mapping. Decoded frames stay on the GPU, and reconstruction uses exact
  integer arithmetic, so performance work never changes the output.
- **Profiles.** Profile 5, Profile 7 (FEL and MEL) and Profile 8 (tested with 8.1 and 8.4).
  For FEL, the enhancement layer is used to rebuild the full picture.
- **Menus and subtitles in Dolby Vision.** Kodi's controls, menus and subtitles are composited
  into the Dolby Vision picture, including over letterbox bars.
- **Light on the GPU.** Only the active picture area of letterboxed films is processed, and
  unchanged on-screen graphics are not reprocessed.
- **Conversions.** Dolby Vision can instead be converted to HDR10 or HDR10+ for HDR TVs
  without Dolby Vision, or to SDR for SDR TVs and projectors (also HDR10, HDR10+ and HLG
  videos); where the chosen output is not available, it falls back to HDR10 and then SDR.
  HDR10+ videos can play as Dolby Vision. Newer, seen on one TV so far (an LG G5) but not
  yet judged by eye: player-led Dolby Vision (mapped to the TV's own Dolby Vision target)
  and HDR10 mapped to a display you describe.
- **QMS refresh switching (experimental)** on HDMI paths that support it, for fewer
  blackouts when the refresh rate changes. VRR support alone does not mean QMS support. It
  is on by default on Intel graphics where the TV reports it, and it can cause picture
  faults: a rapidly flickering picture and a corrupted SDR 24p picture have each been seen
  on one set-up. If the picture flickers or is wrong, turn it off with the kernel option
  `i915.qms=0` (`xe.qms=0` on Lunar Lake and Arc B-series; see
  `yblod/docs/KERNEL-PARAMETERS.md`).
- **Variable refresh rate (experimental)**: Kodi's setting Settings > System > Display >
  Variable refresh rate, shown only on a display that reports variable refresh rate; off by
  default. It has not yet run in YBLOD's checks and may cause the same kind of faults;
  leave it off unless you want to try it.
- **Faster live TV startup**, through fewer stream opens, coordinated display changes and
  less audio buffering.

```text
File -> Kodi / FFmpeg (decode on the GPU, pair layers and metadata)
     -> YBLOD engine (Vulkan compute): rebuild the Dolby Vision picture
     -> menus/subtitles composited, packed for the Dolby Vision HDMI tunnel
        (or converted to HDR10, HDR10+ or SDR)
     -> patched Intel or AMD display driver -> HDMI -> TV display mapping
```

## Settings

**Settings > Player > Dolby Vision:**

- **Output mode:** Dolby Vision (TV-led), Dolby Vision (player-led), Convert to HDR10,
  Convert to HDR10+, Convert to SDR, or Off (Kodi's standard playback of the base layer).
  Only the outputs this display and connection can take are offered. Applies to the next
  video; while one plays, the video OSD's Video settings > Output mode changes it for that
  video alone. **Automatic fallback** (on) uses HDR10, then SDR, where the chosen output is
  not available.
- **HDR10+ videos:** as Kodi plays them, or as Dolby Vision.
- **HDR10 conversion:** Master Reference (the film's own range) or Rendering Reference,
  mapped to a display you describe (peak brightness, black level, colours).
- **SDR display**, **SDR display brightness**, **SDR gamma**, **BT.2020 colours** and **HDR
  videos on an SDR display**, for Convert to SDR.
- **Enhancement layer upscaling** (Annex B or Bilinear), **Dolby Vision metadata** (the
  film's, or with CM4.0 added), **TV peak brightness**, **Remove L2 trims**, and
  **Upscaling** for videos of 1080p and above and for smaller ones (Bilinear, FSR 1, FSR 1 +
  sharpening).
- **Enhanced player information:** video, audio, metadata and GPU usage on the player
  information panel (O).
- **Dolby Vision for the menu:** keeps Dolby Vision on while the menu is shown, so Dolby
  Vision videos start without the TV switching picture mode (needs a 3840x2160 desktop),
  with menu brightness, saturation, gamma and wide colour.

With the settings level set to Expert, two more groups appear:

- **Performance:** reusing unchanged controls and the home screen over video, and
  half-resolution menus (faster with controls open, softer menu text). The reuse is on by
  default and leaves the picture unchanged.
- **Diagnostics:** output verification, a frame timing log and a GPU timing log, for
  troubleshooting.

[Output modes](yblod-engine/docs/intel-dv/OUTPUT-MODES.md) says what each setting does.
These settings take precedence over the same switches in `/storage/.config/native-dv.env`.
Other engine switches can still be set there (restart Kodi afterwards); see the
[engine integration notes](yblod-engine/integration/README.md).

## Requirements and limitations

- For Dolby Vision to the TV: Intel graphics of display generation 12 or later (Tiger Lake
  and newer) or AMD graphics (DCN 1.0 to 3.6), on native HDMI, and a TV that supports
  standard (TV-led) Dolby Vision. Two older Intel boards whose HDMI goes through a
  converter chip are verified too (Dolby Vision only). AVRs and adapters in the HDMI path
  must pass Dolby Vision through. Convert to SDR needs no kernel support and works on any
  connector. See [hardware requirements](yblod-engine/docs/intel-dv/HARDWARE.md).
- Most testing is on an Intel N150 and an 11th-generation Core (Tiger Lake); AMD on one
  Ryzen 5 3500U (Vega 8).
- On low-power Intel GPUs such as the N150, 60 fps Dolby Vision shows about 40 pictures a
  second, and heavy Profile 7 FEL films with the playback controls open fall short of 24
  fps. Non-blocking presentation (off by default) helps both.
- Retired Dolby Vision profiles are not supported. With Output mode Off, Profile 5 shows
  incorrect colours.
- The first boot after an update builds the engine's shaders in the background (about 3
  minutes on an N150); a film started before that finishes may pause briefly.
- Switching between HDR and SDR picture modes can still cause a short blackout.
- Testing covers specific devices, files and TVs. It is not Dolby certification and does
  not guarantee every file, display or skin. Each release's notes list its known issues.

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
  tests, its Kodi, FFmpeg and kernel patches, tools and docs).
- [`yblod/`](yblod/README.md): the distribution (other patches, the LG edition, build and
  release tools, release notes).

See [repository layout](yblod/README.md), [branches, releases and contributing](yblod/docs/BRANCHES.md)
and the documentation indexes of [yblod/docs](yblod/docs/README.md) and
[yblod-engine/docs](yblod-engine/docs/README.md).

## Credits and licences

**CroqueMr.** YBLOD started from CroqueMr's Intel Dolby Vision work
([libreelec-CB1](https://github.com/CroqueMr/libreelec-CB1), earlier intel-dv-libreelec and
libreelec-x86-DV), which showed how to play Dolby Vision on Intel graphics. The engine
compiles source files of his CB1 renderer (the `cb1_*` files in `yblod-engine/src` and
`yblod-engine/vk`, listed with their notices in the engine source notices below), and much
of what YBLOD offers follows his design: the Master Reference conversion, the HDR10+
conversions, the CM4.0 metadata option, the SDR display targets, player-led Dolby Vision
(CB1's LLDV Reference) and HDR10 Rendering Reference. Thank you.

YBLOD also builds on LibreELEC, Kodi, FFmpeg, Intel's graphics and media stack and
libplacebo. The engine's references include ETSI GS CCM 001 and quietvoid's dovi_tool; see
the
[engine source notices](yblod-engine/SOURCES.md), [engine licence](yblod-engine/LICENSE),
and the [integration notices](yblod-engine/docs/intel-dv) and [licences](yblod-engine/licenses).

Dolby, Dolby Vision and the double-D symbol are trademarks of Dolby Laboratories. LibreELEC
is a trademark of Team LibreELEC. This project is independent.
