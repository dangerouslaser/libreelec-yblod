# YBLOD Kodi adapter

The Kodi side of YBLOD's Dolby Vision output is the patch series in
`yblod-engine/patches/kodi/` (Kodi `22.0rc2-Piers`, linked into
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

Switches (`runtime.env`; the settings for the display, brightness, gamma,
BT.2020 colours and HDR videos take precedence over their entries):

| Variable | Default | Effect |
| --- | --- | --- |
| `DV_SDR_OUTPUT` | 1 | 0: no SDR output at all, selected or as the fallback. The way back to 0.5.0's behaviour. |
| `DV_SDR_HDR_SOURCES` | 1 | 0: HDR10, HDR10+ and HLG videos stay with Kodi's tone mapping. |
| `DV_SDR_WHITE`, `DV_SDR_BLACK` | 203, 0 | The display's white (40 to 1000) and black (0: white / 1000) in cd/m2. |
| `DV_SDR_GAMMA` | bt1886 | `2.2` for a 2.2 power. |
| `DV_SDR_TARGET` | default | The display (SDR display, kodi-9963): `default` the three above; CroqueMr's CB1 presets `reference` (100 cd/m2, pure 2.4 power, black 0) and `brightroom` (200, 2.2, 0); `custom`. A library without CB1's targets (`dvvk_sdr_flags`), or a custom value out of range, leaves no SDR output (one log line) rather than another display's. |
| `DV_SDR_CUSTOM_WHITE`, `_GAMMA`, `_BLACK` | 100, 2.4, 0 | The custom display: white 20 to 500 cd/m2, a pure power 1.8 to 2.8, black 0 (a true zero) to 5 cd/m2. |
| `DV_SDR_BT2020` | 0 | 1: BT.2020 colours where the library has `DVVK_SDR_BT2020`, the connector's `Colorspace` has `BT2020_RGB` and the EDID lists BT.2020 RGB; else BT.709. Each picture's gamut is committed with its `Colorspace`; three refused BT.2020 commits fall back to BT.709 from the next picture. |
| `DV_SDR_RANGE` | auto | `auto` follows Kodi's "Use limited colour range"; `full`, `limited`. |
| `DV_SDR_DITHER` | 1 | 0: rounded codes. |

The upscaler (kodi-9964; the engine's `dvvk_set_scaler`, every output mode,
not only SDR): `DV_UPSCALER` for sources of 1080p and above (1920 wide or
1080 high) and `DV_UPSCALER_SD` for smaller ones, `bilinear` (default),
`fsr1` or `fsr1-sharp`, set by Upscaling (1080p and above) and Upscaling
(below 1080p). The method is chosen for each picture's source size and the
engine applies it only to an enlargement; a library without the symbol stays
bilinear, one that refuses a method keeps the one it has (logged). Kodi never
calls `dvvk_set_scaler` while both are bilinear, so the default is the engine
as before.

Player-led Dolby Vision and HDR10 Rendering Reference (kodi-9965, kodi-9966)
have their own section below; their checks are items 14 and 15 here.

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
12. **CB1's displays** (kodi-9963): Reference, Bright room and a Custom
    display (48 cd/m2, gamma 2.6, black 0.05 on the projector) against the
    default on the same title; the log's `Vulkan engine output: SDR (...)`
    names the display. With BT.2020 colours on: a display whose EDID lists
    BT.2020 RGB on Intel and AMD (the `Colorspace` modeset at the first
    picture, Signal `SDR / BT.2020` in player information, the GUI's colours),
    one whose EDID does not (BT.709, the log line), and the fallback when the
    kernel refuses the commit.
13. **Upscaler** (kodi-9964): FSR 1 and FSR 1 + sharpening on a 1080p title
    at 3840x2160, the dropped-frame counter and `DVVK_PROFILE=1` on the UHD
    770, the N150 and Vega 8 at 24p and 60p; Upscaling in player information
    only while the picture is enlarged; a 4K title on the 4K display is not
    touched.
14. **Player-led Dolby Vision** (kodi-9965; nothing of it has been on a
    display, and nothing had ever set `DVBRIDGE_TUNNEL_FORMAT` "lldv"). On a
    Dolby Vision TV whose EDID has a low-latency Dolby block (most LG OLEDs
    from 2019; Sony and others with LLDV), Intel gen12+ and AMD native HDMI:
    - kodi.log at the settings page: `DVBridge output: player-led Dolby
      Vision available: the TV's target P / B cd/m2, primaries ..., VSVDB
      version N, 12 useful bits (the block says 12|10 ...)`. Compare the
      target with the TV's specification. A TV without the block says `not
      available:` and why; the option must then be missing.
    - Select it, play 1917 (P7 FEL), 28 Years Later (P8.1), Gemini Man (60p
      MEL) and a Profile 5 title. Expected: the TV reports Dolby Vision (its
      info banner; LG's "Dolby Vision" picture modes are offered), the
      picture is steady and not black. The log: `DVBridge output: player-led
      Dolby Vision through the tunnel`, `Vulkan engine output: player-led
      Dolby Vision for the TV's target (...)`, `Vulkan engine player-led
      Dolby Vision pts=...: mode 4 eotf 2`. Player information: Playback
      "Dolby Vision (player-led)", Target the TV's values.
    - Against TV-led Dolby Vision of the same scene (OSD > Video settings >
      Output mode): overall brightness and colour should be close; the
      bright highlights of 1917's night scenes and 28 Years Later's dark
      scenes are where they differ. A picture much too dark or too bright
      means the TV maps it again or the target is wrong; colours too
      saturated or washed out mean the primaries or the 4:2:2 matrix.
      Report with the log and a photo of both.
    - 10 bits: `DV_LLDV_BITS=10` in `/storage/.config/native-dv.env` on a TV
      whose block says 10; banding in slow gradients against 12.
    - The GUI over the film (OSD, seek bar, subtitles): white about 203 nits,
      not glaring, colours right.
    - Refusal: a TV whose block has no low-latency interface (or an HDFury
      EDID without it) must not offer it; with it saved, the video falls
      back to Convert to HDR10 (notification "Player-led Dolby Vision is not
      available...") or SDR. The kernel refusing it (`DVBridge: 10
      player-led Dolby Vision commits in a row refused`) must end in the
      title restarting with the fallback's output within a few seconds, not
      a black or frozen screen.
    - Stop, seek, next title, a refresh-rate change (24p after 60p): the
      desktop comes back, no HDMI blanking loop. `DV_LLDV_OUTPUT=0` removes
      the option.
15. **HDR10 Rendering Reference** (kodi-9966; not yet on a display). HDR10
    conversion: Rendering Reference, on an HDR10 TV (Dolby Vision or not)
    with Convert to HDR10, and with Dolby Vision (TV-led) on a TV without
    Dolby Vision (the fallback):
    - kodi.log: `Vulkan engine output: HDR10, Rendering Reference (CroqueMr's
      CB1 Expert) to the display 1000 nits, black 0.0000, P3-D65`, then
      `Vulkan engine HDR10 pts=...: mastering 1000 / 0.0000 cd/m2, MaxCLL 0,
      MaxFALL 0` (the stated display, not the film's mastering). The TV's
      HDR info (HDFury, the TV's service menu) shows the same.
    - With the TV's dynamic tone mapping off, against Master Reference on
      the same scene: with the peak set to the TV's own, highlights keep
      their detail rather than clip; a peak far above the TV's should look
      like Master Reference; 100 nits on the projector.
    - Black presets (OLED, LCD, projector, custom 0.0005) and the three
      gamuts: dark scenes and saturated colours change as expected, greys
      stay neutral. Player information: Playback "HDR10 conversion
      (Rendering Reference)", Target the display.
    - Master Reference (the default) must give the log line and the HDR10
      metadata of before (`HDR10, the Master Reference conversion`).

## Player-led Dolby Vision and HDR10 Rendering Reference

After 0.5.1 (kodi-9965, kodi-9966; the engine's `DVVK_OUTPUT_LLDV` and
`DVVK_HDR10_TARGET`, [vk/README.md](../vk/README.md)): CroqueMr's CB1 maps
Dolby Vision to a stated display, the TV's own (player-led Dolby Vision) or
one the user describes (HDR10 Rendering Reference). Both are new and have
not been seen on a display (item 14 and 15 above). With the settings at
their defaults neither is used: Kodi makes no new engine call and writes no
new DRM property, and the Automatic fallback chooses what it chose before.

**Player-led Dolby Vision** (Output mode "Dolby Vision (player-led)",
`DVBRIDGE::OutputMode::PlayerLed`, 5). Offered in the setting and in the
video OSD's Output mode list only where all of these hold
(`CWinSystemGbmGLESContext::SupportsTunnelLLDV`; kodi.log says which fails
when the answer changes):

- `DV_LLDV_OUTPUT` is not 0, and it has not been refused before in this
  Kodi run;
- the connector is connected, atomic, and has `DVBRIDGE_DV_STANDARD_LAB`
  and the "lldv" value of `DVBRIDGE_TUNNEL_FORMAT` (linux-9901 for i915
  gen12+, linux-9920 for amdgpu; not the converter routes);
- the mode is progressive 3840x2160 (the tunnel's);
- the engine library has the mode (`dvvk_output_modes` bit 4,
  `dvvk_set_display_primaries`, `dvvk_lldv_display_from_vsvdb`; with
  `DV_LLDV_BITS=10` also `DVVK_LLDV_10BIT` in `dvvk_target_flags`);
- the TV's EDID has a Dolby Vision VSVDB with the low-latency interface by
  the kernel's own test (`dvbridge_sink_lldv`, Kodi's copy of the parser),
  and `dvvk_lldv_display_from_vsvdb` on that block returns the TV's target
  (status READY: low-latency 4:2:2, valid luminance, primaries inside
  BT.2020).

Playing, the window begins the tunnel with `playbackTunnelLLDV` and the
target; the engine sets `dvvk_set_display_primaries` (the block's version
and fitted primaries) and then `DVVK_OUTPUT_LLDV` with the peak and black
(`DVVK_LLDV_10BIT` for 10 bits), sends every frame with `dm_options` 0 (the
engine refuses CM4.0 and L2 removal for player-led output; Dolby Vision
metadata's settings do not apply), and marks each picture it made
player-led. The commit that shows such a picture stages
`DVBRIDGE_TUNNEL_FORMAT` lldv with no `HDR_OUTPUT_METADATA` and no HDR10+
(the kernel then sends the Dolby VSIF with the low-latency bit and the AVI
YCbCr 4:2:2 BT.2020 limited range); `dvvk_output_signal` (mode 4, eotf 2,
the useful bits) is only logged. It is never chosen by the fallback, and a
display without it takes the fallback as Dolby Vision (TV-led) would on a
TV without Dolby Vision: Convert to HDR10, then Convert to SDR (an HDR base
layer to an HDR display as it is), or the base layer with Automatic
fallback off; the notification says player-led is not available.

When it cannot start: the engine refusing the TV's primaries or target
(`Vulkan engine refused player-led Dolby Vision (...)`), or ten refused
player-led commits in a row (`DVBridge: 10 player-led Dolby Vision commits
in a row refused`), withdraw it until Kodi restarts, with a notification,
and restart the title where it was with the fallback's output. Until then
no picture of another kind is sent with the lldv signal. A title whose
pictures the engine refuses one by one plays as its base layer, as for
Dolby Vision (kodi-9961).

**HDR10 Rendering Reference** (HDR10 conversion: Master Reference, the
default, or Rendering Reference, with Display peak brightness 50 to 10000
nits, Display black level OLED 0 / LCD 0.005 / projector 0.05 / custom 0 to
0.5 nits, Display colours P3-D65 (default), BT.2020, BT.709). Shown where
this connection has the HDR10 output and the library `DVVK_HDR10_TARGET`,
or while Rendering Reference is saved. It applies to every use of the
engine's HDR10 output: Convert to HDR10, the fallback to it, and Convert to
HDR10+ on a TV without HDR10+ or after its fallback to HDR10 (HDR10+ output
itself is not mapped). The engine gets `{DVVK_OUTPUT_HDR10,
DVVK_HDR10_TARGET, peak, black, {gamut}}` and the HDR static metadata the
TV gets is `dvvk_output_signal`'s: the stated display's primaries, max and
min luminance, MaxCLL and MaxFALL 0. A library without the flag, a value
out of range from `native-dv.env`, or the engine refusing it give the
Master Reference conversion (one log line): an HDR10 picture all the same.

Player information shows the target (Target) for both, and Playback
"Dolby Vision (player-led)" or "HDR10 conversion (Rendering Reference)".

Videos without Dolby Vision do not take either: an HDR10, HDR10+ or HLG
video plays as before (as Kodi shows it, converted to SDR, or as Dolby
Vision TV-led through "HDR10+ videos" and the OSD's Convert to Dolby
Vision, which stay TV-led only).

| Variable | Default | Effect |
| --- | --- | --- |
| `DV_LLDV_OUTPUT` | 1 | 0: player-led Dolby Vision is never offered, also where it is saved (the fallback's output then). |
| `DV_LLDV_BITS` | 12 | 10: 10 useful bits in the 12-bit carrier (`DVVK_LLDV_10BIT`), for a TV whose low-latency 4:2:2 takes 10. No setting. |
| `DV_HDR10_TARGET` | 0 | 1: Rendering Reference (HDR10 conversion). |
| `DV_HDR10_TARGET_PEAK`, `_BLACK`, `_GAMUT` | 1000, 0, p3 | The display: 50 to 10000 cd/m2; 0 to 0.5 cd/m2; `p3`, `bt2020`, `bt709`. |

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

## History

The OpenCL engine's port and qualification (YBLOD 0.2 to 0.3, Kodi
`63063c8e`), which 0.4.0 removed, and their reports are in
[history/](history/README.md).

The adapter code uses GPL-3.0-or-later; existing Kodi and bridge notices
remain applicable. See yblod-engine's LICENSE and SOURCES.md, installed with
the engine package.
