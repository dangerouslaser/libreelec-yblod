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
| Off | Kodi's ordinary playback of the base layer: HDR10 or SDR as the stream's base layer is, without the enhancement layer. Profile 5 has no compatible base layer and its colours are wrong. |

**Convert to HDR10** is offered only where it can be had: an HDR10 display
on a connector with linux-9928's `DVBRIDGE_TUNNEL_FORMAT` and its `hdr10`
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
The output targets progressive 3840x2160.

## Playback information

**Enhanced player information** replaces the stock information panel. Press **O** to open or close it; **Esc/Back** closes it. Disable the option to restore the stock panel. The existing **Ctrl+Shift+O** diagnostic remains unchanged.

The panel separates source metadata, reconstruction and output. SDR, HDR10 and HLG use a compact video/audio/rendering layout without DV sections. Static HDR metadata appears only when available. Dolby Vision sources retain their detailed panel, including during the HDR10 conversion. Missing or inapplicable fields are hidden. FEL presence is not reported as successful reconstruction until a corresponding frame is presented. Drop and skip values are Kodi's own counters; pattern correction is not a dropped-frame counter.

The bottom-aligned panel fits its tallest visible column, with no close-action footer. No Dolby logos or speaker diagram are included. Metadata refresh is limited to twice per second while the panel is open.

## Diagnostics

Output selection, metadata origin, presentation failures and restoration are recorded automatically in kodi.log. A playback-health summary records native frame counters, video queue state and Kodi render-engine usage every 10 seconds, including with the panel closed. Existing bounded kernel diagnostics remain available. No per-frame metadata dumps or image readbacks are added. See [playback diagnostics](PLAYBACK-HEALTH.md).
