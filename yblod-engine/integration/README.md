# YBLOD Kodi adapter

The Kodi side of YBLOD's Dolby Vision output is the patch series in
`yblod-engine/patches/kodi/` (Kodi `e6192109`, linked into
`projects/Generic/patches/kodi/`), `kodi-9950` to `kodi-9960`; see
[KODI-PATCHES.md](../../yblod/docs/KODI-PATCHES.md) for what each holds and
where the older patch numbers below went. Since 0.4.0 it drives one renderer,
the Vulkan engine (`yblod-engine/vk`). The engine's adapter
(`kodi-9956-dv-vulkan-engine-adapter.patch`) is `CDVPrivateSource` /
`CDVPrivateVulkan`; the window
(`WinSystemGbmGLESContext`) commits its scanout buffers with the tunnel's
signal.

## Build and runtime

Use YBLOD's normal Generic x86-64 image build. Kodi's recipe depends on
`yblod-engine-vk` (the engine library, built with cargo and glslc), which also
installs `runtime.env` as `/usr/lib/kodi/native-dv.env`, the Kodi service
drop-in `20-native-dv.conf` and `dv-diagnostics`. Optional
`/storage/.config/native-dv.env` entries override the packaged values.
`runtime.env` holds only what the Vulkan path reads (audited from the code at
0.4.0); its comments name each variable's reader.

Kodi's Settings > Player > Dolby Vision applies its settings as environment
overrides at start and whenever a setting changes (`DVEngineSettings.h`); for
those the setting wins over `native-dv.env`. See
[OUTPUT-MODES.md](../docs/intel-dv/OUTPUT-MODES.md) for the menu and what
each entry sets. The hidden setting `yblod.build` (always true) lets skins
detect YBLOD with `System.GetBool(yblod.build)`; `dvbridge.settingsversion`
records the settings migrations done.

If the engine's library is missing or of another ABI, Dolby Vision titles
play as plain base-layer video until Kodi restarts, with one notification and
one log line; there is no second renderer. An engine that does not start, or
fails more often than it is started again (below), costs only the title that
tried it: that title restarts as plain playback and the next one tries the
engine again. After three such titles in one Kodi run the engine stays off
until Kodi restarts, with the notification.

## SDR output

After 0.5.0 (kodi-9958 to kodi-9960; the engine's `DVVK_OUTPUT_SDR`):
Dolby Vision, and HDR10, HDR10+ and HLG videos, converted by the engine for
a display without HDR and shown by the bridge as an ordinary RGB picture.
[OUTPUT-MODES.md](../docs/intel-dv/OUTPUT-MODES.md#convert-to-sdr) says what
it does and how it was checked. How it differs from the tunnel outputs in
Kodi:

- The bridge runs at the display mode's size (kodi-9958): scanout buffers,
  the GUI raster and the engine's canvas (`dvvk_create_canvas`). The tunnel
  outputs are still only begun at 3840x2160.
- `CDVBridgeState::Capture(drm, false)`: no tunnel property is needed; where
  the connector has one it is staged off, with no HDR metadata and default
  colorimetry. `max bpc` and `Broadcast RGB` are left as the desktop has
  them. The restore after the video puts back what was captured, as for the
  tunnel.
- No menu output, no held stop, no mode change left to the bridge's first
  commit: those exist to make one HDMI signal change of several, and SDR
  output changes no signal.
- Which output a video gets is `CWinSystemGbmGLESContext::DVOutput()`
  (Dolby Vision videos: the selected mode, or the fallback order) and
  `PlainSourceSDR()` (videos without Dolby Vision). The log says so:
  `DVBridge output: SDR (...)`, `Vulkan engine output: SDR (...)`, and
  `DVBridge output: mode N is not available on this display; using M`.

Switches (`runtime.env`; the settings for brightness, gamma and HDR videos
take precedence over their entries):

| Variable | Default | Effect |
| --- | --- | --- |
| `DV_SDR_OUTPUT` | 1 | 0: no SDR output at all, selected or as the fallback. The way back to 0.5.0's behaviour. |
| `DV_SDR_HDR_SOURCES` | 1 | 0: HDR10, HDR10+ and HLG videos stay with Kodi's tone mapping. |
| `DV_SDR_WHITE`, `DV_SDR_BLACK` | 203, 0 | The display's white (40 to 1000) and black (0: white / 1000) in cd/m2. |
| `DV_SDR_GAMMA` | bt1886 | `2.2` for a 2.2 power. |
| `DV_SDR_RANGE` | auto | `auto` follows Kodi's "Use limited colour range"; `full`, `limited`. |
| `DV_SDR_DITHER` | 1 | 0: rounded codes. |

### To check on a display

Seen on a display once: Convert to SDR on an LG TV through AMD graphics
(Ryzen 5 3500U), 1917 at 203 cd/m2 with BT.1886, no dropped frames. The
rest below is still to be checked. An SDR-only TV is not needed: any TV
shows an SDR signal, and an HDFury Arcana can present an EDID without HDR and
Dolby Vision blocks, which is what the fallback has to see. A projector is a
separate check.

1. **It starts.** A Dolby Vision title (Profile 5, 7 FEL, 8.1) with Output
   mode "Convert to SDR", on native HDMI (Intel gen12+, AMD), on a
   DP-to-HDMI converter route, on the NUC7's LSPCON and on DisplayPort. The
   first flip without the tunnel property is the open question on each.
2. **Fallback.** EDID without HDR and Dolby Vision: the same titles with
   Output mode left at Dolby Vision (TV-led) play as SDR, with one
   notification. EDID with HDR10 but no Dolby Vision: Convert to HDR10 is
   used; a Profile 8.1 title with "Automatic fallback" off plays as its
   HDR10 base layer. `DV_SDR_OUTPUT=0`: the base layer, as in 0.5.0.
3. **Levels.** Black bars and a ramp with Kodi's limited range setting off
   and on, against Kodi's own SDR playback of an SDR video on the same
   input: bars, the GUI and the film must sit at the same levels as Kodi's
   pages (the kernel's `Broadcast RGB` is not touched). If only the film is
   off, `DV_SDR_RANGE=full|limited` says which way.
4. **Gamma and brightness.** BT.1886 against 2.2, and 100 / 203 / 300 nits,
   on a TV in a dim room; 100 nits on the projector. Shadows too dark with
   BT.1886 on a bright TV is the case for 2.2.
5. **Banding and dither.** Slow gradients (sky, fades) at 8 bits; the
   dither pattern is fixed, so look for a visible static texture on flat
   areas at 1080p. `DV_SDR_DITHER=0` for comparison.
6. **GUI over the film.** OSD, seek bar, subtitles (text and PGS): placed
   and coloured as on Kodi's own pages, steady through scene changes, and
   right with limited range.
7. **Modes.** A 1920x1080 display; a 3840x2160 one; a 4K title on the
   1080p display; a 1080p title on the 4K one; refresh-rate switching
   (24p, 60p) and a resolution switch through the whitelist during a video
   (the bridge ends and begins again at the new size); a mode the engine
   does not take (1366x768) plays through Kodi.
8. **Stop, seek, next title.** The desktop comes back with its own levels;
   Dolby Vision then HDR10 then SDR titles in one session; a title after an
   engine restart.
9. **HDR videos.** An HDR10, an HDR10+ and an HLG video with "HDR videos on
   an SDR display" on each setting: the picture against Kodi's Hable, and
   the dropped-frame counter. A software-decoded HDR10 video still plays
   (Kodi's shader). On an HDR TV with Kodi's "Adjust display HDR mode" off,
   HDR10 is converted; with it on, it is passed through as before.
10. **Speed** (`DVVK_PROFILE=1`): the N150 at 3840x2160 24p (1917, 28 Years
    Later), 60p (Gemini Man) and Profile 5; the same at 1920x1080; the
    first SDR picture's hitch when `yblod-dv-prepare` has not run.
11. **VRR** (kodi-9990). On a FreeSync display with Kodi's variable refresh
    rate setting on: the refresh-rate changes before and after an SDR-output
    video, which the tunnel outputs have been through and SDR output has not.

## Presentation (0.5.0)

0.5.0 reworked how pictures reach the engine and the display (formerly
patches yblod-40 to -49, the numbers below; now in kodi-9953, kodi-9956 and
kodi-9957). What changed, and the switch for each change that reading the
code cannot prove (`runtime.env`):

- The engine gets the decoded VAAPI surface directly (`-40`): no GL texture,
  no `vaSyncSurface`, no EGL fence, no YUV shaders for a Dolby Vision title.
  A picture that is not a VAAPI surface (software decoding) never enters the
  Dolby Vision path and plays through the ordinary renderer (`-41`).
- The engine knows a surface by its id. The adapter resets it when either
  layer's surfaces come from another pool (`-42`), so the engine ships with
  `DVVK_SURFACE_CHECK=0`; `1` brings back its per-frame export and compare.
- A picture asked for again unchanged stays on screen (`-43`,
  `DV_PRIVATE_SKIP_REPEATS`): no submission and no commit for a pause or for
  the repeats of 24p on a 60 Hz mode. The log counts them ("frame held").
- The GUI buffer is handed to the engine only when Kodi drew into it (`-44`,
  `DV_PRIVATE_GUI_UNCHANGED_SKIP`).
- An engine failure is answered by draining, destroying and starting the
  engine again (`-45`): twice without a thousand good frames in between, then
  the title is given back to plain playback. If the drain fails, work of the
  engine may still read the decoded surfaces: nothing is released and no
  frame is taken (the log says so at FATAL) until a later drain succeeds,
  tried when the display is handed back and when the adapter closes.
- A refused restore of the ordinary display is tried again (`-46`).
- `-47` and `-48` are fixes and housekeeping without a switch.

### Queued flips (`DV_PRIVATE_NONBLOCK`, shipped 0)

With blocking commits Kodi's work on a picture and the GPU's must fit in one
refresh together. `-49` commits the pictures of a stable scanout with
`DRM_MODE_ATOMIC_NONBLOCK` and an out-fence instead. It has not run on a
display: enable it only for the hardware test below.

State per picture, on the render thread:

1. Prepare: the adapter leases a scanout slot that is neither on screen nor
   queued (three buffers), and the engine submits; its fence goes on the
   buffer. Only the frame before the newest is waited for when two are in
   flight.
2. Present, stable scanout: wait one refresh (the queued flip's out-fence, or
   without a queued flip the next vertical blank), then commit with NONBLOCK
   and `OUT_FENCE_PTR`. The slot becomes "queued"; the kernel waits for the
   buffer's fence and the vertical blank.
3. The next Prepare or Present sees the out-fence signalled (flip numbers in
   `CDRMAtomic`) and only then calls the queued buffer the one on screen.
4. Present, anything else (first commit, modeset, HDR10 signal change, the
   picture after a rejected commit, HDR10+ output, restore, menu, startup
   signal): wait for the queued flip (1 s at most), then the blocking,
   fully validated commit of 0.4. `EBUSY` on a queued commit: the same
   request is committed blocking.
5. A picture held as a repeat waits the same one refresh and commits
   nothing.

Every picture so takes two refreshes from the render manager's choice to the
screen, and `GetFrameLatencyAdjustment()` reports one refresh more latency,
which keeps audio and video in step.

Assumptions about the kernel, to confirm on i915 and amdgpu:

- A non-blocking commit waits for the framebuffer's implicit (dma-resv)
  write fence before the flip, as the blocking commit does today.
- `-EBUSY` is returned only while the previous commit's flip has not
  completed, and the CRTC out-fence signals at that completion with the
  vertical blank's timestamp.
- A stable frame needs no modeset: the transport properties are restaged
  with unchanged values. (A changed HDR10 metadata blob may be refused
  without ALLOW_MODESET; the next commit then validates fully, as in 0.4.)
- The kernel's own fence timeout (i915: 10 s) bounds a flip whose GPU work
  never finishes; Kodi's waits are 250 ms per picture and 1 s before a
  blocking commit, and a flip that is still queued after that fails the
  commit into the usual retry delay.
- The Dolby Vision tunnel's and the HDR10+ kernel patches do not depend on
  the commit being blocking (HDR10+ output is never queued).

Hardware test (N150 60p is the case it is for; also 24p, AMD, and a title
with the OSD open):

- Log: `DV flips queued=N: on_time= late= blocking= busy= timeouts=
  queued_to_vblank_ms mean= max=` every 600 flips; with
  `DV_PRIVATE_FLIP_TRACE=1` one line per flip with the framebuffer, the
  vertical blank's time and `refreshes_since_last`.
- It works when, in steady playback, `late`, `busy` and `timeouts` stay 0
  (or near it) and `on_time` grows by 600 per summary: every refresh got a
  new picture. Before: flip gaps of 1,2,1,2 on the N150 at 60p.
- Kodi's dropped and skipped frame counters stay 0; the picture order is
  right at seeks, pause and resume, frame steps and stop; audio stays in
  sync (compare with `DV_PRIVATE_NONBLOCK=0` on the same title).
- Each start, refresh change, HDR10 signal change, menu handover and stop
  shows `blocking` increasing and no "flip-pending" failure.
- HDR10+ output: unchanged from 0.4 (never queued); its packets stay with
  their pictures.
- An EDID/hotplug during playback and a GPU hang (if one can be provoked)
  end in the retry or recovery paths, not in a frozen loop.

## History (0.2-0.3)

The sections below record the OpenCL engine's port and
qualification (Kodi `63063c8e`, 2026-10). They describe that engine, which
0.4.0 removed; the reports stay for reference.

## Current status

The complete Generic image has built and booted on the N150. The installed
engine has passed selected current-profile controls/recovery checks, and initial
GPU timestamp baselines are available in
[QUALIFICATION-20261009.txt](QUALIFICATION-20261009.txt). The reproduced early
P7 presentation gaps were subsequently fixed and retested in
[STARTUP-HANDOFF-20261009.txt](STARTUP-HANDOFF-20261009.txt), which also records
remaining controls-open frame drops in a 59.94 Hz sample. These results apply
to the exact images identified in each report. Pre2 packaging and final smoke
results are recorded in [PRE2-20261009.txt](PRE2-20261009.txt). A subsequent
visually reproduced VM menu-return defect and the pre3 target-recreation fix
are documented in [PRE3-20261009.txt](PRE3-20261009.txt); pre2's timing/signalling
checks did not establish correctness of the visible menu image.

The unchanged standalone source passes all three Release-mode CPU contract
tests with GCC 14.2 and CMake 4.4.4: specialization admission, geometry and
output-slot ownership. These are not GPU or Kodi playback tests.

The patch was `kodi-9999-yblod-03-native-source.patch` (now part of
`kodi-9956-dv-vulkan-engine-adapter.patch` and
`kodi-9957-dv-renderer-window-and-build.patch`).
Generic builds apply it after the existing YBLOD QSV and menu patches and
install the engine and dependencies through Kodi's package recipe. This is
integration source; use the separately packaged pre-release for installation.

The subsequent `kodi-9999-yblod-04-native-startup.patch` (now in kodi-9957)
establishes a valid black DV signal before releasing playback startup. The
final `kodi-9999-yblod-05-remove-legacy-settings.patch` removed Quick Sync scaling and
Match Dolby hardware levels from the settings UI. Both legacy behaviors are
forced off, including for profiles with old saved values. This does not change
native reconstruction or disable hardware video decoding.

## Qualification boundaries

The report above records packaged-image profile, timing, reference, cold-cache,
EOF, ownership/recovery and menu/QMS smoke checks. These are bounded tests, not
all-media certification. The menu-off/passthrough P7 startup fix passed the
documented A/B and packaged-boot checks; 59.94 Hz controls-open playback still
requires work.
Optical menu appearance, transition blackout and physical audio synchronization
are not proven by driver readbacks. Pre-release testing is not general certification.

The route targets 3840x2160 progressive output with admitted source geometry
and metadata. HDR bitmap overlays and native composite screenshots remain
unsupported. Retired profiles are unsupported; profile 20 is deferred.
The existing engine tests are not independent Dolby conformance tests.

`MEASUREMENTS.md` is historical context comparing the prior and newer CB1
adapters. It is **not** a measurement of this YBLOD port.

The adapter code uses GPL-3.0-or-later; existing Kodi and bridge notices
remain applicable. See yblod-engine's LICENSE and SOURCES.md, installed with
the engine package.
