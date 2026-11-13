# Video output

Settings are in **Kodi > Settings > Player > Dolby Vision**. Playback
preferences apply to the next video. Since 0.4.0 every Dolby Vision picture
is made by YBLOD's Vulkan engine (`yblod-engine/vk`); there is no second
renderer.

## Output mode

| Output mode | Result |
| --- | --- |
| Dolby Vision (TV-led) | Default. The engine reconstructs the picture (FEL included) and sends it with frame-matched Dolby Vision metadata through the DV tunnel (RGB 8-bit container); the TV's Dolby Vision processing maps it. |
| Convert to HDR10 | The engine converts Dolby Vision to HDR10 with the Master Reference conversion (CroqueMr's CB1 Reference Basic mapping) and sends BT.2020 PQ through the tunnel as 12-bit YCbCr 4:2:2 (`DVBRIDGE_TUNNEL_FORMAT` hdr10, linux-9928), with HDR static metadata from the film (L6 or its source peak, L9 primaries). |
| Convert to HDR10+ | Dolby Vision to HDR10+ (CroqueMr's CB1 method): the engine sends the Master Reference reconstruction in BT.2020 PQ **without** tone mapping, through the tunnel as for HDR10 (same static metadata), and with each picture an HDR10+ vendor InfoFrame (`HDR10PLUS_METADATA`, linux-9932) in the same atomic commit as that picture. The TV applies the HDR10+ curve. The metadata is made from the picture's Dolby Vision L1 (L3 folded in), L2 or L8 trims where their response fits one HDR10+ curve for a 992-nit reference, and statistics the engine measures on the film area of each picture (maxRGB histogram, average, channel maxima), one picture late at most. |
| Convert to SDR | For a TV or projector without HDR (after 0.5.0). The engine converts the reconstructed picture to an ordinary BT.709 picture, scene by scene from the Dolby Vision metadata (L1), and the bridge shows it as 8-bit RGB with no tunnel and no HDR signalling, at the display's own mode. YBLOD's conversion, not Dolby's: see [Convert to SDR](#convert-to-sdr). |
| Off | Kodi's ordinary playback of the base layer: HDR10 or SDR as the stream's base layer is, without the enhancement layer. Profile 5 has no compatible base layer and its colours are wrong. |

**Convert to HDR10** is offered only where it can be had: an HDR10 display
on a connector with `DVBRIDGE_TUNNEL_FORMAT` (linux-9901, linux-9920) and its `hdr10`
value (native HDMI: Intel display gen12 and later, AMD), and an engine with
HDR10 output. It is hidden on the converter routes: the DP-to-HDMI
converters (linux-9930) have no such property; the NUC7's LSPCON in
level-shifter mode (linux-9931) has it but its kernel takes only Dolby
Vision, so after ten refused HDR10 commits on a connection that never
took one, the option is withdrawn until Kodi restarts and the title plays
without conversion (notification). The converter routes get Dolby Vision
or nothing (plan decision 3). The GL HDR10 conversion of 0.3 (libplacebo
spline tone mapping in a 10-bit framebuffer) is gone with the compatibility
renderer.

**Convert to HDR10+** is offered where Convert to HDR10 is and, in
addition, the connector has linux-9932's `HDR10PLUS_METADATA` (native HDMI
only, never the converter routes), the TV's EDID has an HDR10+ Vendor-Specific
Video Data Block, and the engine has HDR10+ output (`dvvk_hdr10plus_packet`).
The packets use the application version the TV's block states (version 1 or
0). Details:

- The first pictures after the output starts carry no packet (the engine has
  no finished picture's statistics yet); the first packet turns HDR10+ on,
  which the kernel treats as a modeset.
- A picture whose metadata cannot be represented as HDR10+ (CB1's rules)
  ends HDR10+ for the rest of the video: the packet is cleared and the engine
  continues with the HDR10 conversion. Three refused HDR10+ commits do the
  same; where none ever worked, the option is withdrawn until Kodi restarts
  (notification).
- HDR10+ is turned off with the output (the restore commit at stop).
- The HDR10+ curve is an approximation of the Dolby Vision trims by design
  (CB1's own documentation): the curve is fitted for a 992-nit reference
  display, not the TV's peak, and checked against the trims on grey and
  coloured probes.
- With a TV that has no HDR10+, the setting plays as Convert to HDR10.

Not yet tested on an HDR10+ TV (no HDR10+ TV in the lab): compile-checked,
with the engine's statistics checked against a CPU reference (PR #30).

The HDR10 conversion is the engine's. The author's check: within one 12-bit
code of a CPU double-precision map of the same conversion; the comparison
against CB1 Reference Basic on the four reference titles and the TV test are
0.4.0 workstream C validation, not yet done.

## Output mode during playback

After 0.5.0 (0.5.1). While a video plays: OSD > **Settings** > **Video
settings** > **Output mode**. The choice is for the playing title only: the
settings above do not change, and the next title, or the same one played
again, has the settings' output.

| Playing video | Choices |
| --- | --- |
| Dolby Vision | Dolby Vision, Convert to HDR10, Convert to HDR10+, Convert to SDR |
| HDR10+ | HDR10+ (original), Convert to Dolby Vision, Convert to SDR |
| HDR10 | HDR10 (original), Convert to Dolby Vision, Convert to SDR |
| HLG | HLG (original), Convert to SDR |
| SDR | none: the entry is not shown |

A choice is listed only where it can be had now, with the same tests as the
settings: Dolby Vision on a Dolby Vision TV and connection, Convert to
HDR10 and HDR10+ where the Output mode setting offers them, Convert to SDR
where the engine has the SDR output for the display's mode ("HDR videos on
an SDR display"'s `DV_SDR_HDR_SOURCES=0` removes it for videos without
Dolby Vision), an HDR10+, HDR10 or HLG video's own format where Kodi
sends that video to the display as HDR. With fewer than two choices the
entry is not shown; a title that plays without the engine (it did not
start, or it refused the title's pictures) has none.

- **HDR10+ (original)** is what Kodi does with HDR10+ videos: HDR10 with
  the static metadata (no HDR10+ passthrough), so there is no separate
  HDR10 choice for an HDR10+ video.
- **Convert to Dolby Vision** of an HDR10+ video is the "HDR10+ videos:
  Dolby Vision" conversion below. Of an HDR10 video it is new: every
  picture gets the same metadata, made from the video's static metadata
  (`dvvk_hdr10_to_dovi`, the SDR output's: mastering range, L6, L9 from
  the mastering primaries, no L1), and goes out as Dolby Vision Profile 8.1
  without an enhancement layer; the TV's Dolby Vision processing maps it
  with that range for the whole video.
- **Convert to SDR** of a video Kodi would show as HDR uses the SDR output
  as on an SDR display.

Switching between Convert to HDR10 and Convert to HDR10+ of a Dolby Vision
video happens while it plays (as the HDR10+ fallback does). Any other
change restarts the title where it is, as when the engine fails to start,
and closes the dialog. kodi.log says `DVBridge: video OSD: this title's
output A -> B` with how it switched, and, after a restart, `DVBridge: this
title's output from the video OSD: B`.

## Convert to SDR

Not part of 0.5.0. Built and checked on the build host's GPU; **not yet seen
on a display** (the hardware list is in
[integration/README.md](../../integration/README.md#sdr-output)).

**What it is.** The HDR10 conversion's recipe with another target: libplacebo's
spline tone curve on IPT's I, driven by the picture's L1 (the static source
range when a picture has none), now compressing to the display's white;
libplacebo's perceptual gamut mapping from the title's mastering primaries
(L9; P3-D65 when it has none) to BT.709; then the display's inverse EOTF. Dolby's
100-nit trims (L2, L8) are not applied. The result is 8-bit R'G'B', dithered
with a fixed 64x64 blue-noise pattern (the same bytes on every run); the
stream's black (the letterbox) is one exact value. Every pixel has its own
chroma: the 4:2:2 sample on even pixels, the mean of it and the next one on
odd pixels. Kodi's GUI is blended after the conversion, so it does not move
with the film's scenes.

**Where it is offered.** Wherever the engine has the output and the display's
mode is one the engine takes as its canvas: both sides multiples of 4, 64 to
4096, progressive. So 1920x1080 and 3840x2160 displays, on any connector
(native HDMI, the converter routes, DisplayPort): the picture is ordinary KMS
and needs nothing from the kernel. A mode the engine does not take (1366x768)
plays through Kodi as before. A 4K video on a 1080p display is resized by the
engine (the enhancement layer is then not used: it is below the picture's
resolution anyway).

**The display it converts for.**

| Setting | What it sets |
| --- | --- |
| SDR display brightness | White of the display the picture is made for: 100 (projector), 150, 203 (default) or 300 nits (`DV_SDR_WHITE`). 203 is BT.2408's and libplacebo's reference and keeps more of the highlights apart; 100 gives brighter mid-tones. The display's own brightness control is not touched. Black is white / 1000. |
| SDR gamma | BT.1886 (gamma 2.4, default) or a 2.2 power (`DV_SDR_GAMMA`). |
| Automatic fallback | On by default. When the display does not have the selected output mode, the next one it has is used: Dolby Vision, then Convert to HDR10, then Convert to SDR. One exception: a display Kodi sends HDR to (Kodi's "Adjust display HDR mode" on, HDR in the EDID) still gets an HDR10 or HLG base layer from Kodi as it is, since that keeps more of the picture than an SDR conversion; Profile 5 and the SDR-compatible profiles are converted. A notification says once which output is used. Off: a video whose output mode is missing plays as its base layer, as before. |
| HDR videos on an SDR display | **YBLOD's SDR conversion** (default): HDR10, HDR10+ and HLG videos take the same conversion where Kodi would otherwise tone-map them (the display is not sent HDR): HDR10+ scene by scene from its metadata (`dvvk_hdr10plus_to_dovi`), HDR10 and HLG with one curve for the whole video from the mastering display's peak (`dvvk_hdr10_to_dovi`; HLG as BT.2100's 1000-nit display would show it). **Kodi's tone mapping**: Kodi's shader, which is cheaper on a slow GPU (`DV_SDR_HDR_SOURCES=0` does the same). |

RGB range follows Kodi's "Use limited colour range" (`DV_SDR_RANGE`), for the
picture and the GUI over it, exactly as Kodi's own pages do; the link's depth
and the kernel's `Broadcast RGB` stay what the desktop has.

**What Kodi's shader still plays.** Whatever the engine does not take:
software-decoded, interlaced and 3D videos, pictures over 3840x2160, and any
video when the engine cannot start. Its default method is Hable now (it was
"off" for every profile, which shows HDR10 washed out); a saved "off" is
changed once.

**What "correct" means here.** There is no reference SDR picture to match
byte for byte (CB1 has no SDR circuit, Dolby's is not public). Three checks,
all on the build host's UHD 770:

1. *The engine against itself* (`tools/sdr-check.sh`): 78 pictures of 39
   configurations (FEL, MEL, Profile 8.1 and 5; white 100 and 203, gamma 2.2,
   limited range, with and without the GUI; canvases 3840x2160, 1920x1080,
   1280x720 and 4096x2160; HDR10 and HLG sources), every sample within one
   8-bit code of a CPU double-precision map of the same reconstructed
   picture, and each picture's hash in `tools/sdr.sha256`. Real HLG, HDR10+
   and Profile 8.4 clips, outside the script: the same with BT.1886; with a
   2.2 power three of nine pictures have a few samples (at most 0.00011 %)
   two or three codes off.
2. *libplacebo itself* (`tools/sdr-oracle.c`, real `pl_render_image` with the
   same recipe on the same reconstructed picture): four titles at three
   displays. Largest difference of a rounded sample 1.1 codes on a BT.1886
   display (3 on a 2.2 one, in near-black where that curve is steepest);
   mean dE ITP 0.41 to 1.03, never above 3.2; the dithered picture's 2x2
   means differ by 0.12 to 0.16 of a code. HDR10 and HLG sources, decoded by
   libplacebo's own matrix and HLG: mean dE ITP 0.55 to 0.81, never above
   2.7.
3. *Sanity without a GPU* (`dvvk-map-test --ramp`, `tools/sdr-eval`): grey
   ramps monotonic, white only at the source's peak, black at code 0, greys
   neutral.

The oracle is not built with the engine (it needs libplacebo with a GPU
backend). On the build host: compile `tools/sdr-oracle.c` against CB1's
patched libplacebo e2972fdd (`-lplacebo -lEGL -lgbm -lm`, the CB1 tree's
toolchain and sysroot), dump a picture twice with `dvvk-bench` (`--dump`
with the tunnel output, and `--output sdr --no-dither`), write its
parameters with `dvvk-map-test --output sdr --oracle FILE` on the picture's
metadata (`dvvk-bench --metadata`), run `sdr-oracle --chroma linear FILE
DV.dump OUT.f32` in an image root that has that libplacebo, and compare with
`dvvk-sdr-compare --oracle OUT.f32 SDR.dump`.

**Cost.** GPU time per picture on the UHD 770, as fast as it goes
(`DVVK_PROFILE`), 3840x2160 unless noted:

| Title | Dolby Vision | Convert to HDR10 | Convert to SDR | SDR with the GUI | SDR at 1920x1080 |
| --- | --- | --- | --- | --- | --- |
| 1917 (P7 FEL, 24p) | 8.4 ms | 10.5 | 10.9 | 12.4 | 3.9 |
| 28 Years Later (P8.1, 24p) | 3.7 | 4.7 | 7.1 | 9.9 | 3.8 |
| Gemini Man (P7 MEL, 60p) | 5.4 | 7.0 | 8.9 | 12.1 | 4.6 |
| Dolby Vision landscape demo (P5, 60p) | 5.6 | 12.4 | 9.3 | 13.0 | 4.7 |
| 28 Years Later's base layer as HDR10 | | | 10.5 | | |
| the same codes as HLG | | | 9.1 | | |

SDR costs more than the tunnel: every pixel has its own chroma and its own
lookup, and the samples the 3D LUT cannot hold to a third of a code (3 to
11 % of a frame) are computed exactly. The N150 is about twice as slow (not
measured for SDR): expect 24p titles at 3840x2160 to fit and 60p ones to be
at the limit (about 18 ms of 16.7); "HDR videos on an SDR display" can be
set to Kodi's tone mapping there.
The first SDR picture of an engine compiles its pipelines when
`dv-prepare` has not (about 0.2 s once; cached afterwards).

## Video

| Setting | What it sets |
| --- | --- |
| HDR10+ videos | Shown on a Dolby Vision TV when the engine has the conversion. **Native HDR10+** (default): as Kodi plays them, i.e. HDR10 (no HDR10+ passthrough in 0.4.0). **Dolby Vision**: HDR10+ videos (HDR10 base layer with single-window HDR10+ in each picture) play as Dolby Vision Profile 8.1 without an enhancement layer, with metadata made for each picture from its HDR10+ by the decoder (`dvvk_hdr10plus_to_dovi`, CroqueMr's CB1 method: identity composer, L1 from the validated MaxSCL and the percentiles, L6 from the static metadata; no trims made up, the HDR10+ curve not translated). A video whose first HDR10+ picture cannot be represented (several windows, no usable peak) plays as HDR10; a later picture that cannot be keeps the previous picture's metadata. Dolby Vision (TV-led) output only. |
| Enhancement layer upscaling | **Annex B (Master Reference)**: the filters of Dolby's published reference (ETSI CCM Annex B), with CB1 Master Reference's processing (siting, 4:2:0 reshaping, Annex B EL and 4:2:2 filters, metadata order) for pictures shown at their own size; scaled pictures use YBLOD's own processing. **Bilinear**: YBLOD's own processing with the engine's bilinear EL upscale (`DVVK_EL_BILINEAR`) for every picture (`DV_EL_SCALER`). |
| Dolby Vision metadata | **Original**: the film's metadata. **CM4.0 auto**: neutral CM4.0 levels (L3, L9, L11, L254) added to CM2.9 films where CroqueMr's CB1 rules call for it: L1 within the TV's peak plus 20 %, or, without a known TV peak, a mastering peak up to 1000 nits. **CM4.0 always**: added to every CM2.9 film. No trims are made up. Dolby Vision output only (`DV_VULKAN_CM4`). Off by default (plan decision 6). |
| TV peak brightness | For CM4.0 auto: from the TV's EDID (desired content max luminance), or 400 to 4000 nits (`DV_VULKAN_TV_PEAK`). |
| Remove L2 trims | Leaves the film's CM2.9 trims out of the metadata (`DV_VULKAN_NO_L2`). Dolby Vision output only. |
| Enhanced player information | The player information panel below. |

## Menu output

**Dolby Vision for the menu** keeps the Dolby Vision output on while the menu
is shown (graphics-only frames with static metadata, packed from Kodi's GUI
on the GPU; not the engine), with its brightness, saturation, gamma and wide
colour settings. Dolby Vision (TV-led) only.

## Performance and diagnostics (expert)

| Setting | What it sets |
| --- | --- |
| Reuse unchanged controls / the home screen over video | Kodi reuses its drawn GUI while it does not change (`DV_PRIVATE_GUI_CACHE`, `DV_PRIVATE_GUI_CACHE_HOME`). |
| Half-resolution menus | Kodi draws the GUI over videos at 1920x1080 and upscales it (`DV_PRIVATE_GUI_HALF`). |
| Verify output | Every 60th frame rendered again by the engine's reference route and compared (`DVVK_VERIFY=60`). |
| Frame timing log | Kodi's first-frame timing lines and the engine's per-frame deadline JSON (`DV_PRIVATE_FRAME_TIMING`, `DVVK_DEADLINE_TRACE`). |
| GPU timing log | GPU time per engine pass over 120 frames (`DVVK_PROFILE`). |

Removed in 0.4.0 (they only affected the OpenCL engine or the compatibility
renderer): Native Dolby Vision engine, Vulkan engine, Colour upscaling,
Nearest-neighbour enhancement layer, Process only the picture area, Fast
on-screen controls, Reuse reshaping tables, Prepare frames ahead. A one-time
settings migration drops their saved values.

## When the engine cannot start

If the Vulkan engine's library is missing or of another ABI, or the engine
does not start (no Vulkan device for the display), Dolby Vision titles play
as plain base-layer video (as with Off) until Kodi restarts, with one
notification and one log line. A title that was starting restarts where it
was (plan decision 4).

## Rendering information

The enhanced Player information panel separates video/audio, DV metadata and rendering
statistics. Profile, level, configuration version and CM metadata are distinct.
Pixel format describes decoded-source chroma subsampling (for example YUV 4:2:0), not the hardware surface. Source bit depth comes from the decoded
picture and is separate from the output framebuffer and HDMI transport.
GPU render (Kodi) reports this process's render-engine occupancy from DRM fdinfo,
including the visible overlay. It is not whole-device utilization, power or a
measurement of the hardware video decoder. Sampling is limited to twice per
second while the enhanced panel is open; unavailable counters are hidden.

## Output precision

Dolby Vision, HDR10 and HDR10+ all leave Kodi through the tunnel's 8-bit RGB
framebuffer, which is a transport container, not the picture's precision:
Dolby Vision is the 12-bit tunnel signal, HDR10 and HDR10+ 12-bit YCbCr 4:2:2.
Output precision is not user-selectable. A connector's maximum bit-depth
property is a negotiation limit, not proof of the transmitted bit depth.
The tunnel outputs target progressive 3840x2160. Convert to SDR is what it
looks like: an 8-bit RGB picture, dithered, at the display's mode.

## Playback information

**Enhanced player information** replaces the stock information panel. Press **O** to open or close it; **Esc/Back** closes it. Disable the option to restore the stock panel. The existing **Ctrl+Shift+O** diagnostic remains unchanged.

The panel separates source metadata, reconstruction and output. SDR, HDR10 and HLG use a compact video/audio/rendering layout without DV sections. Static HDR metadata appears only when available. Dolby Vision sources retain their detailed panel, including during the HDR10 conversion. Missing or inapplicable fields are hidden. FEL presence is not reported as successful reconstruction until a corresponding frame is presented. Drop and skip values are Kodi's own counters; pattern correction is not a dropped-frame counter.

The bottom-aligned panel fits its tallest visible column, with no close-action footer. No Dolby logos or speaker diagram are included. Metadata refresh is limited to twice per second while the panel is open.

## Diagnostics

Output selection, metadata origin, presentation failures and restoration are recorded automatically in kodi.log. A playback-health summary records native frame counters, video queue state and Kodi render-engine usage every 10 seconds, including with the panel closed. Existing bounded kernel diagnostics remain available. No per-frame metadata dumps or image readbacks are added. See [playback diagnostics](PLAYBACK-HEALTH.md).
