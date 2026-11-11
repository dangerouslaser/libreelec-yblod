# SDR output plan: Dolby Vision and HDR on SDR TVs and projectors

Written 2026-11-11. Research and scope only: nothing is implemented, no build was run, no box was contacted. Base: `feature/yblod-0.5.0` at `8b5608259b`.

The request: GPU tone mapping of HDR and Dolby Vision to SDR for local playback on a display that is SDR (an SDR TV, a projector), with Intel QSV / AMD AMF suggested as the means. The finding: the vendor paths cannot do it for Dolby Vision at all, and the fork already has the hard part (the reconstruction and a baked 3D-LUT colour map) in its Vulkan engine. The recommendation is a third output mode of that engine. What Kodi does today, with numbers, is in section 0; the decisions that are the owner's are in section 1.

Every statement below is from the code at that commit (Kodi `e6192109` with the fork's 18 patches replayed, the engine in `yblod-engine/vk`), from the numeric work described in 0.3, or from the cited public sources. What could not be established without hardware is listed in section 7.

## 0. Findings

### 0.1 What an SDR display gets today

"SDR display" for Kodi means `CWinSystemGbm::IsHDRDisplay()` is false: the connector has no `HDR_OUTPUT_METADATA` property or the EDID has no HDR static metadata block (type 1). The user can also turn off `winsystem.ishdrdisplay` on a display that has one; `SetHDR()` then returns false for HDR10 and HLG.

Dolby Vision goes to the engine only when `NativeDVEligible()` (`WinSystemGbmGLESContext.cpp`) says so: output mode Dolby Vision needs `SupportsNativeDVOutput()` (the EDID's Dolby block parsed by `dvbridge_parse_edid` as Standard, the `DVBRIDGE_DV_STANDARD_LAB` connector property, a 3840x2160 progressive mode); the HDR10 and HDR10+ modes need `SupportsTunnelHDR10()`, whose first test is `IsHDRDisplay()`. On an SDR display every mode is unavailable, and there is no fallback from one mode to another (also not from Dolby Vision to HDR10 on an HDR10-only TV). The stream is then an ordinary video: the enhancement layer and the RPU are not used, the decoder's picture carries the base layer's own colour signalling, and `CRendererVAAPIGLES` (a `CLinuxRendererGLES`) draws it with `gles_yuv2rgb_basic.frag`.

| Content | What is shown on an SDR display today |
| --- | --- |
| Dolby Vision Profile 5 | **Wrong colours.** The base layer is IPT-PQ-C2 with unspecified VUI; Kodi takes it as BT.709 Y'CbCr (`DVDVideoCodecFFmpeg.cpp`: unspecified primaries become BT.709), no tone mapping, no reshaping. `OUTPUT-MODES.md` says the same for "Off". |
| Profile 7 FEL / MEL | The HDR10 base layer alone (no enhancement layer, no RPU), as plain HDR10 below. |
| Profile 8.1 | The HDR10 base layer, as plain HDR10 below. The RPU's L1 is not used. |
| Profile 8.4 | The HLG base layer, as HLG below. |
| HDR10 | Kodi's GLES tone mapping (0.2), if a method is selected. With the method "off" only the gamut conversion runs, on PQ code values: a dim, flat picture (100 cd/m2 grey shown at 20 % of the display's white, 1000 cd/m2 at 50 %). |
| HDR10+ | As HDR10. The dynamic metadata is not used. |
| HLG | No tone mapping (the test is PQ only). The HLG signal is treated as gamma 2.4, converted to BT.709 and re-encoded with 1/2.2. Watchable, because HLG is built to be shown on an SDR display. |

### 0.2 Kodi's GLES tone mapping

Where: `system/shaders/GLES/2.0/gles_yuv2rgb_basic.frag` (and `_bob`, `gles310_yuv2rgb_filter.frag`) with `gles_tonemap.frag` inserted; uniforms from `VideoShaders/YUV2RGBShaderGLES.cpp`, `ToneMappers.cpp`, `ConversionMatrix.cpp`; the decision in `CLinuxRendererGLES::CheckVideoParameters`. It runs for VAAPI-decoded surfaces (the VAAPI GLES renderer imports NV12/P010 planes and uses these shaders). It does not run in `CRendererDRMPRIMEGLES` (hard-wired off) or direct-to-plane.

- **When:** only for `color_transfer == SMPTE2084 && color_primaries == BT2020`, HDR passthrough off, method not "off". Not for HLG.
- **Methods:** off, Reinhard, ACES, Hable (video OSD > Video settings > Tone mapping, plus a "parameter" 0.1 to 5, default 1.0; per video, with a default in `guisettings.xml`). **By the code a new profile's default is "off"**: upstream commit `0bb1747a9a4b` ("Change default tone map method to Hable", 2024-03-10) set the constructor default to OFF and made Hable only the value for a saved file without the key, and a new profile's first save writes the constructor's value. Not confirmed on a box (section 7).
- **Metadata:** static only. Reinhard: `param = log10(100) / log10(MaxCLL)` (or the mastering maximum), 0.7 without either. ACES/Hable: a "luminance value" = 0.5 x min(MaxCLL, mastering max) + 0.2 x max(...) + 0.3 x MaxFALL, or the mastering maximum, or 400. Nothing dynamic: no HDR10+, no Dolby Vision L1.
- **Gamut:** before any tone mapping the shader does `pow(rgb, 2.4)`, the BT.2020 to BT.709 matrix, `max(0, .)`, `pow(1/2.2)` **on the PQ code values**, as if PQ were a gamma-2.4 signal. ACES and Hable then apply the PQ EOTF to the result. Out-of-gamut colour is clipped per channel, never mapped.
- **Output:** display-referred R'G'B' written to the framebuffer (Reinhard's result as is; ACES `pow(0.27)`; Hable `pow(1/2.2)`), values above 1.0 clipped by the framebuffer. Full range unless `videoscreen.limitedrange`. The surface is rebuilt for the video's depth (10-bit for HDR10); dithering exists (`videoscreen.dither`) but is off by default.
- **Precision:** `precision mediump float` in a GLSL ES 1.00 shader. On Mesa's Intel and AMD drivers that is ordinarily 32-bit float; not checked on hardware.

### 0.3 The numbers

Method. Kodi's exact shader math was written in Python from the sources above. The reference is the engine's own vendored libplacebo (`yblod-engine/vk/yblod/placebo`, CB1's patched e2972fdd), compiled on the Mac into a small harness that does what `dv_map.c` does for HDR10 (`pl_color_space_infer_map`, `pl_tone_map_generate` with libplacebo's default constants, the IPT hull desaturation) plus what an SDR target adds: `pl_gamut_map_sample` with `pl_gamut_map_perceptual` from BT.2020 to BT.709, target BT.1886 at 100 or 203 cd/m2 with libplacebo's default 1000:1 black. The tone curve is `spline` (CB1 Reference Basic's, and what the engine's HDR10 mode uses), with `bt2390` and `bt2446a` beside it to show how far two legitimate curves are apart. Both Kodi's and the reference's results are shown on the same display model (BT.1886, white 100 or 203, black white/1000) and compared as displayed light, in dE ITP (BT.2124; 1 is about a just noticeable difference). Test titles: mastering peak = MaxCLL = 1000 / 4000 / 10000, MaxFALL 180 / 400 / 1000. The harness is not in the repository (one document was asked for); 0.3's method paragraph and `dv_map.c` are enough to rebuild it.

Grey ramp, 1000 cd/m2 title on a 100 cd/m2 display (displayed cd/m2; `clip` = the framebuffer value exceeded 1.0):

| in | ref spline | ref bt2390 | Kodi off | Reinhard | ACES | Hable |
| --- | --- | --- | --- | --- | --- | --- |
| 0.005 | 0.10 | 0.10 | 0.15 | 0.15 | 0.25 | 0.13 |
| 1 | 1.03 | 1.48 | 1.53 | 1.91 | 1.56 | 0.93 |
| 10 | 7.07 | 10.7 | 6.00 | 9.61 | 7.19 | 6.02 |
| 50 | 25.8 | 36.3 | 14.1 | 27.3 | 31.2 | 25.5 |
| 100 | 38.8 | 54.3 | 19.6 | 41.0 | 54.0 | 44.1 |
| 203 | 54.7 | 74.2 | 26.8 | 60.3 | 79.2 | 69.4 |
| 400 | 72.1 | 90.5 | 35.4 | 84.9 | 96.8 | 94.5 |
| 600 | 83.7 | 97.0 | 41.3 | clip | clip | clip |
| 1000 | 100 | 100 | 49.8 | clip | clip | clip |

Where Kodi's curves reach white and clip everything above (grey, input cd/m2):

| Title metadata | Reinhard | ACES | Hable |
| --- | --- | --- | --- |
| peak/MaxCLL 1000, MaxFALL 180 | 564 | 477 | 471 |
| peak/MaxCLL 4000, MaxFALL 400 | 208 | 1702 | 1682 |
| peak/MaxCLL 10000, MaxFALL 1000 | 124 | 3995 | 3949 |
| mastering 1000, MaxCLL 400, MaxFALL 80 | 1364 | 277 | 273 |
| no metadata | 754 | 262 | 259 |

Mean / max dE ITP against the spline reference, display 100 cd/m2 (the last row of each block is the distance between the two reference curves, i.e. what "a different but legitimate curve" costs):

| Title | Method | Grey ramp | Natural colours | P3 primaries/secondaries | BT.2020 primaries/secondaries |
| --- | --- | --- | --- | --- | --- |
| 1000 | off | 26 / 49 | 39 / 59 | 52 / 73 | 40 / 69 |
| 1000 | Reinhard | 12 / 25 | 16 / 32 | 24 / 59 | 18 / 64 |
| 1000 | ACES | 15 / 26 | 14 / 32 | 17 / 58 | 10 / 35 |
| 1000 | Hable | 7 / 19 | 10 / 23 | 14 / 47 | 9 / 35 |
| 1000 | (bt2390 vs spline) | 13 / 23 | 22 / 23 | 15 / 25 | 14 / 24 |
| 4000 | Reinhard | 24 / 47 | 42 / 50 | 34 / 62 | 21 / 60 |
| 4000 | ACES | 18 / 54 | 44 / 55 | 32 / 54 | 31 / 54 |
| 4000 | Hable | 7 / 12 | 11 / 15 | 15 / 39 | 12 / 35 |
| 4000 | (bt2390 vs spline) | 7 / 21 | 8 / 21 | 5 / 19 | 8 / 23 |

On a 203 cd/m2 display Hable is 17 / 36 (grey) and 28 / 39 (natural) for the 1000 title, against 13 / 33 and 25 / 33 between the two references.

In plain words:

- **Off** (the apparent default): flat and dim, never reaches white, colours at about half saturation, P3 blue turned 20 degrees towards purple.
- **Reinhard:** works on PQ code values, not light. Natural colours come out at 51 to 62 % of the reference's chroma (washed out). Its white point moves the wrong way with MaxCLL: a 4000 cd/m2 title clips everything above 208 cd/m2, a 10000 one above 124.
- **ACES:** raises black (0.005 cd/m2 shown at 0.25 against 0.10), and scales the whole picture by the "luminance value": a 10000 cd/m2 title is far too dark (100 cd/m2 grey shown at 8 % of white, against 36 %).
- **Hable:** the only usable one. Its tone scale is as close to the reference as another reference curve is. Its faults are structural: it clips at half the "luminance value" (471 cd/m2 for a 1000 title; 259 without metadata: every highlight above that is flat white), it compresses each channel on its own (bright skin and sky keep 61 to 67 % of the reference's chroma), and it inherits the gamma-domain conversion.
- **All methods:** the gamma-domain conversion makes ACES/Hable tone-map the wrong luminance (10 cd/m2 is read as 6.7, 100 as 74, 1000 as 838) and bends saturated colours: P3 blue at the 203 level is exactly BT.709's blue (0, 0, 223 cd/m2) but reaches the tone curve as (7.1, 1.0, 196); its hue is off by 7 degrees under ACES/Hable at 203 and by 30 to 38 at 1000. No gamut mapping, no dynamic metadata, no HLG.
- **HLG** (no tone mapping, gamma-domain conversion): 6 mean / 15 max dE ITP against the reference on a 203 cd/m2 display, 15 / 28 on a 100 one, hue within 2 degrees. Acceptable.
- **What dynamic metadata is worth** (reference, 1000 title, 100 cd/m2 display, a 100 cd/m2 grey): 38.8 with static metadata; 85.7 in a scene whose L1 says max 120 / avg 12; 45.4 for max 400 / avg 40; 20.8 for max 1000 / avg 150. A static curve is wrong by a factor of two in dark scenes. With L1, `spline` and libplacebo's `st2094-10` (the public form of Dolby's curve) agree within 2 cd/m2 everywhere.

**Answer for the owner:** Kodi's GLES tone mapping is not good enough to be the answer. It is tolerable for HDR10 only with Hable selected by hand (and HLG needs nothing), it is wrong in its colour conversion for every method, it clips highlights hard, and it ignores every dynamic format. It cannot show Profile 5 at all. As a fallback for pictures the engine does not take it should stay, with its default changed (work item 9).

### 0.4 The engine's HDR10 map, and what assumes a PQ BT.2020 output

Today (`dv_map.c`, `dvvk_map.h`, `shaders/common/dv_map.glsl`, `map_bake.comp`, `map_fixup.comp`, `pack.comp` MAP, `src/map.rs`, design in big-fella `docs/hdr10-output.md`): one function of the reconstructed 12-bit Y'CbCr: the RPU's matrix to the source's nonlinear R'G'B' (L'M'S' for Profile 5), PQ EOTF, `rgb_to_lms` to linear BT.2020; if a curve is needed, IPT, a 256-entry tone LUT on I (`pl_tone_map_spline`, the frame's L1 as max/avg, output peak = L6's mastering maximum, i.e. **no compression to a display**), the hull desaturation; PQ OETF; BT.2020 Y'CbCr; 12-bit limited-range codes. `mode->peak_nits > 0` is refused ("target-display modes: not yet"), and the map is refused unless the gamut map is a no-op (BT.2020 to BT.2020 always is). The GPU bakes the function into a 65x65x65 LUT indexed by the nonlinear source cube whenever the parameters change (a scene's L1), marks the cells whose trilinear error exceeds 0.5 of a 12-bit code and computes the pairs falling in them exactly in a second pass. Result: every sample within one 12-bit code of the CPU's double-precision map. The GUI is blended **before** the map, in the Dolby Vision source domain.

Everything that assumes PQ BT.2020 output:

| Where | Assumption |
| --- | --- |
| `dv_map.c` `dvvk_map_plan` | modes HDR10/HDR10PLUS only; target `PL_COLOR_PRIM_BT_2020` / `PL_COLOR_TRC_PQ`; peak from L6; `peak_nits > 0` refused; gamut map must be a no-op; `signal.eotf = 2` |
| `dv_map.c` `dvvk_map_rgb`, `dvvk_map_ycc`, `dvvk_map_set_black`; `dv_map.glsl` `map_rgb`, `map_ycc`, `map_codes`, `map_q` | ends in the PQ OETF; BT.2020 non-constant-luminance coefficients; 12-bit limited Y'CbCr codes clamped 16..4079 |
| `dv_map.glsl` `map_pair`, `map_word`, `map_unword`; `map_fixup.comp`; `pack.comp` `finish()` | the tunnel's pixel word (12-bit Y and C in XRGB8888), a pair's chroma taken from its even sample |
| `map_bake.comp`, `map.rs` `BAKE_THRESH` | nodes hold Y'CbCr codes / 4096; threshold in 12-bit codes |
| `pack.comp` overlay order, `STATS` | GUI blended in the source domain before the map; statistics read BT.2020 PQ limited codes |
| `engine.rs` | `map` only for the two modes; output slots are linear XRGB8888 **3840x2160** (`CANVAS_W/H` constants, about 40 uses) |
| `dv_engine_vk.h`, `capi.rs` | `DVVK_OUTPUT_*` = 0..2; `dvvk_hdr_signal` is PQ static metadata |
| Kodi `DVPrivateVulkan.cpp` | `WantedOutputMode`, `SelectOutputMode`, the published HDR10 signal |
| Kodi `WinSystemGbmGLESContext.cpp` | `NativeDVEligible` (three modes), `SupportsTunnelHDR10` (`IsHDRDisplay()`), `BeginDVBridge` (3840x2160, 8-bit surface, `SetGuiCompositing(SMPTE2084)`), `OutputModeOptions` |
| Kodi `DVBridgeState.cpp` | `Capture()` fails without `DVBRIDGE_DV_STANDARD_LAB` and stages it as 1; `SetSignal` knows dolby-vision and hdr10 |
| Kodi `WinSystemGbm.cpp` `FlipDVBridgePage` | 3840x2160 buffer and mode, CTA rates only |

### 0.5 Presentation and the kernel

The Dolby Vision and HDR10 modes flip the engine's own buffers on the primary plane (`FlipDVBridgePage`) with the tunnel's properties staged by `CDVBridgeState`. Every kernel check in linux-9901 (i915) and linux-9920 (amdgpu), link policy and scanout policy, applies only while `DVBRIDGE_DV_STANDARD_LAB` is 1. With it 0, or on a connector that has no such property, a flip of an XRGB8888 buffer is ordinary KMS, the same as Kodi's own pages. **An SDR presentation needs nothing from the kernel**, on either driver, and is not limited to the tunnel's connectors (it also works on the converter routes, DP, and Intel display before gen12). What it needs is in Kodi: `CDVBridgeState::Capture()` must not require the property, and must stage an ordinary signal (the tunnel property 0 where it exists, `HDR_OUTPUT_METADATA` 0, `Colorspace` Default; `max bpc` and `Broadcast RGB` left as the desktop has them, unlike the tunnel, which forces 8 and Full).

Size: the engine's canvas and Kodi's bridge are 3840x2160 only. A 4K SDR TV or 4K projector is covered; a 1080p display is not, and most SDR displays are 1080p (work item 7).

### 0.6 The vendor paths

- **Intel VA-API / QSV VPP.** `VAProcFilterHighDynamicRangeToneMapping` (libva `va_vpp.h`): the metadata type enum has `None` and `HDR10` only; the filter's parameters are the input and output static metadata, nothing else. FFmpeg's `vf_tonemap_vaapi.c` refuses any input that is not PQ ("Only support HDR10 as input"), passes mastering display and content light level, outputs NV12 or P010, and has no curve, peak or gamut option. intel/media-driver's README lists "HDR10 TM" for ICL, TGLx (which includes ADL-N: the N150 is covered), DG1, DG2, MTLx, LNL, BMG, PTL, and only in the full-feature build (LibreELEC builds it so: `ENABLE_NONFREE_KERNELS=ON`, media-driver 26.4.1); not on KBL and older, not on EHL/JSL. It runs in VEBOX (fixed function). No Dolby Vision awareness anywhere: no RPU, no reshaping, no IPT, no enhancement layer. So it could at best replace Kodi's shader for plain HDR10, with no control over the result, and never touches the cases that are wrong today.
- **AMD AMF.** The brief's "needs AMD's proprietary stack" is partly out of date: since AMF 1.4.34 (2024) the converter, scaler and encoder are "stable" on Mesa's RADV (GPUOpen AMF README). The AMF runtime itself is still AMD's closed binary, released for RHEL, Ubuntu and SLES. And AMF does have HDR tone mapping, though Jellyfin documents none: `AMF_VIDEO_CONVERTER_INPUT_TONEMAPPING` (copy, AMD, linear, gamma, Reinhard, BT.2390) with static `AMFHDRMetadata`, used by FFmpeg's `vf_vpp_amf.c` for PQ input. Still static HDR10 only, no Dolby Vision, a closed blob in the image, and a second colour pipeline that could never be matched against a reference.
- **Verdict:** the recommendation stands. Neither can reconstruct Dolby Vision, neither uses dynamic metadata, neither can be held to the owner's accuracy standard. One idea worth keeping from Intel's side: media-driver also exposes a VEBOX 3D LUT filter on TGL and later, which could apply the engine's baked LUT to plain HDR10 without render-engine time on an N150. Intel only, interpolation not ours; not part of this plan.

## 1. Decisions for the owner

1. **Presentation route.** Recommended: the existing direct scanout of the engine's buffers, as an ordinary (non-tunnel) XRGB8888 framebuffer, the engine composing the GUI (A). Alternative: the engine's picture as a texture drawn by Kodi's GLES renderer, GUI by Kodi (B). A reuses the hardened path and puts the engine's exact bytes on the wire; B works at every display mode on day one and costs a GL pass per frame and a second presentation path. See section 3.
2. **1080p displays.** A needs the engine's canvas to be a run-time size (work item 7) before a 1080p TV or projector is covered. In scope for the first release, or 2160p displays first?
3. **Target white, default.** 203 cd/m2 (libplacebo's and BT.2408's SDR reference; more highlight separation, darker mid-tones) or 100 (BT.1886 practice; brighter mid-tones). Proposed: a setting "SDR display brightness" 100 / 150 / 203 / 300, default 203 for a TV, with 100 recommended in the help text for projectors.
4. **Transfer.** BT.1886 (gamma 2.4 with libplacebo's 1000:1 black) or pure gamma 2.2. Proposed: a setting "SDR gamma" 2.4 (default) / 2.2. sRGB is not a video display curve; not offered.
5. **Tone curve.** `spline` driven by L1, the same recipe as the HDR10 mode (recommended: one recipe, one oracle), or `st2094-10`. With L1 they differ by under 2 cd/m2 (0.3).
6. **Dolby's 100-nit trims (L2, L8 with target display 1).** Off (recommended, as decided for HDR10: no CM4 mapping), or applied. They are creative trims on top of Dolby's own curve, which is not public; on another curve they are an approximation, and CB1's Expert at T=600 crushed 64 % of 28 Years Later to black with one (`cb1-hdr10-ref-oracle` note).
7. **Automatic fallback.** When the selected output mode is not available on the display, play Dolby Vision as SDR through the engine instead of the base layer (recommended; it is what makes Profile 5 right without a visit to the settings), or only when "Convert to SDR" is selected.
8. **HDR10, HDR10+ and HLG on an SDR display.** Leave on Kodi's shader with Hable as the default (work item 9, small), or move to the engine (work item 10). Recommended: 9 now, 10 as the second step, HDR10+ first because its conversion to Dolby Vision metadata already exists.
9. **Dither.** A fixed pattern (byte-reproducible by the CPU reference; recommended) or one that changes per frame.
10. **Setting names.** "Convert to SDR" in Output mode; "SDR display brightness"; "SDR gamma". New strings in 45000-45999.
11. **Chroma for the RGB output.** The pair's co-sited chroma for both pixels (as the HDR10 mode; cheapest) or linear interpolation for the odd pixel (better; the lookup's chroma half is then per sample, not per pair).

## 2. Recommended design

SDR is a third output of the engine, `DVVK_OUTPUT_SDR`, reached through the same optional `dvvk_set_output_mode` (no ABI or soname change; `peak_nits` is the target white, flags for gamma 2.2 and limited range).

- **Mapping** (`dv_map.c`): the HDR10 recipe with another target. Source: as today, with L9's mastering primaries as the gamut mapper's input gamut. Target: BT.709, BT.1886, white = the setting, black = white / 1000. Tone: `pl_tone_map_spline`, libplacebo's constants, the frame's L1 (static source metadata when there is none), now really compressing. Gamut: `pl_gamut_map_perceptual` from the vendored `gamut_mapping.c` (its first real use), as a LUT generated once per title and target with `pl_gamut_map_generate` and sampled by the bake and the exact path, as libplacebo's own shader does. Output: the target's R'G'B' (BT.1886 inverse, or 1/2.2).
- **LUT:** the same domain and size (65 points on the nonlinear source cube), nodes holding R'G'B' codes. The marked-cells scheme stays; the exact function now includes one sample of the gamut LUT. The threshold is half an output code: at 8 bits that is 8 of today's 12-bit codes, so far fewer cells should need the exact pass (to be measured, work item 1).
- **Output:** ordinary full-range R'G'B' in XRGB8888 (limited range when Kodi's `videoscreen.limitedrange` is on, as its own renderer does), 8-bit with dither, each pixel from its own luma and its pair's chroma (decision 11). The stream's black is an exact constant, as today.
- **GUI:** blended **after** the map, a plain "over" of the premultiplied sRGB GUI on the output R'G'B'. Before the map it would go through a curve that changes with every scene's L1 and pump with the film. This is also cheaper than the source-domain blend (no colour cache).
- **Kodi:** output mode "Convert to SDR" (value 4), offered wherever the engine has it and the mode is the canvas size; the bridge's scanout with an ordinary signal (0.5); no kernel change. The Kodi shader stays for whatever the engine does not take (software decoding, interlaced, 3D, sizes over 3840x2160), with Hable as its default.
- **Later, optional:** 12-bit SDR through the tunnel (`DVBRIDGE_TUNNEL_FORMAT` `sdr`: AVI YCbCr 4:2:2 BT.709 limited). The smallest engine change of all (the HDR10 byte layout with other matrices), exact bytes to the TV and no dither, but a kernel patch on both drivers, native HDMI on gen12+/AMD only, and sinks that take YCbCr 4:2:2. Recorded, not planned.

## 3. Alternatives rejected

| Alternative | Why not |
| --- | --- |
| Intel VPP / QSV tone mapping | HDR10 only, static, no controls, no Dolby Vision (0.6). |
| AMD AMF | The same limits, plus a closed runtime in the image (0.6). |
| Leave everything on Kodi's shader | Profile 5 stays wrong; FEL, L1 and HDR10+ stay unused; the shader's colour conversion is wrong and it clips (0.3). |
| Fix Kodi's shader instead (convert in linear light, a BT.2390 curve, no clip) | A real, small improvement for plain HDR10, but still static, still not Dolby Vision, and a third colour pipeline with its own maths and no oracle. Not needed if work item 10 is done; the fallback if it is not. |
| B: engine picture drawn by Kodi's GLES renderer | Every mode and Kodi's GUI for free, but a full-screen GL pass per frame on the N150, a second presentation path beside the bridge (0.4.0 removed the last one on purpose), dither and final bytes no longer the engine's. The fallback if the run-time canvas (work item 7) proves too invasive. |
| 4K buffer on a 1080p mode through the plane scaler | No engine change, ordinary KMS, but the engine still computes 4K, and whether i915 and amdgpu take a 2:1 downscale at every rate is hardware-dependent. An interim option for decision 2, to be tried with a TEST_ONLY commit on hardware. |
| A libplacebo renderer in Kodi (as 0.3 had) | Removed in 0.4.0; float reconstruction, not the Master Reference. |

## 4. Work items, in dependency order

Sizes are working days for one person who knows the engine, and are estimates.

| # | Item | Touches | Verified by | Uncertain | Size |
| --- | --- | --- | --- | --- | --- |
| 1 | **SDR map on the CPU.** `DVVK_OUTPUT_SDR` in `dvvk_map_plan`: target colour space, tone parameters, gamut parameters and the generated gamut LUT; `dvvk_map_rgb`/`dvvk_map_sample` for the SDR target (double precision, the gamut LUT sampled as the GPU will); `dvvk_map_set_black`; `dvvk-map-test --output sdr`. | `yblod/dv_map.c`, `include/dvvk_map.h` (`dvvk_map_gpu` grows: static asserts, `src/map.rs`), `include/dv_engine_vk.h`, `tools/dvvk-map-test.c` | `cargo test`; the grey ramp and patches of 0.3 reproduced by `dvvk-map-test` (same numbers as the research harness); HDR10 mode's parameters byte-identical to today's | Which interpolation libplacebo's shader uses on the gamut LUT at e2972fdd (the reference must use the same); the share of marked cells at an 8-bit threshold | 4 |
| 2 | **SDR map on the GPU.** `dv_map.glsl`: output transfer, gamut LUT sample, R'G'B' codes; `map_bake.comp` nodes and threshold in output codes; `map_fixup.comp` and `pack.comp` MAP: RGB words, dither, the letterbox constant; engine plumbing (`engine.rs`, `map.rs`, `capi.rs`), the gamut LUT's texture. | the shaders named, `src/engine.rs`, `src/map.rs`, `src/capi.rs`, `build.rs` | `dvvk-bench --output sdr` dumps against item 1's CPU map: at most one output code with dither off, byte-identical pattern with it on; `golden.sh` 90 + 18 hashes unchanged (Dolby Vision and HDR10 untouched) | float `pow` across GPUs (HDR10 mode is within one code between Intel and AMD, not bit-identical: expect the same) | 6 |
| 3 | **GUI after the map.** A pack overlay variant that blends the GUI on the output R'G'B' (and the limited-range scale); the source-domain prepare pass skipped in SDR. | `shaders/pack.comp`, `overlay_prepare.comp` use, `src/engine.rs`, `src/overlay.rs` | golden.sh's overlay picture in SDR against a CPU blend; the film outside the GUI byte-identical to the no-overlay frame | damage tracking and the GUI caches (`DV_PRIVATE_GUI_CACHE*`) with the new order | 3 |
| 4 | **Tools and hashes.** `dvvk-bench --output sdr`, `dvvk-sdr-compare` (after `dvvk-hdr10-compare`), SDR cases in `golden.sh` as tolerance checks rather than hashes if GPUs differ by a code. | `yblod-engine/vk/tools` | runs on the build host's GPU and the N150 | none | 2 |
| 5 | **Kodi: the mode and the plain scanout.** `OutputMode::SDR`; `NativeDVEligible` and `OutputModeOptions`; `CDVPrivateVulkan::HasSDR`, `WantedOutputMode`, `SelectOutputMode` (white, gamma, range from settings); `CDVBridgeState` capture and staging without the tunnel; `BeginDVBridge` without PQ GUI compositing; the automatic fallback (decision 7) with one notification. A new patch in 9950-9989, or folded into 9953/9955/9956/9957 by owner. | `DVOutputSettings.h`, `WinSystemGbmGLESContext.cpp`, `WinSystemGbm.cpp`, `DVBridgeState.cpp`, `DVPrivateVulkan.cpp` | compile check with Kodi's flags; on hardware: section 5 | a library without SDR must be detected (`dvvk_set_output_mode` returning -1 at engine start, or a new optional symbol); VRR modes (the tunnel refuses them, a plain scanout need not) | 5 |
| 6 | **Settings, strings, player information.** `dvbridge.sdrpeak`, `dvbridge.sdrgamma`, the new Output mode value and help texts (ids in 45000-45999); the panel shows "SDR (BT.709), converted" for the output. | `settings.xml`, `strings.po` (9955), `GUIDialogPlayerProcessInfo.cpp`, `IncludesDVProcessInfo.xml`; skin.estuary.yblod if it lists modes | `check_strings.py`; the settings page on a box | none | 2 |
| 7 | **Run-time canvas (1080p and other modes).** The engine's canvas as a create-time size (`CANVAS_W/H`, about 40 uses; the shaders already take `w`, `h`); Kodi's bridge sized by the mode (`BeginDVBridge`, `FlipDVBridgePage`, the GUI target, `DVPrivateVulkan`'s GUI buffer). The tunnel modes stay 3840x2160. | `src/engine.rs`, `src/capi.rs`, `src/overlay.rs`, `src/damage.rs`, `dv_engine_vk.h`; the Kodi files of item 5 | golden.sh unchanged at 3840x2160; new 1920x1080 SDR cases; a 4K title on a 1080p mode is the resized pack (an exact 2:1 is a 2x2 box average in `source_linear`) | scaled pictures use YBLOD's own processing, not the CB1 contract; other ratios are bilinear; the resolution whitelist picks the mode (a 1080p title on a 4K display may be switched to 1080p: allowed in SDR, unlike the tunnel) | 7 |
| 8 | **Oracle on the build host.** The owner's `cb1-hdr10-ref` tool (`feature/cb1-hdr10-oracle`) with an SDR target: CB1's Basic recipe through real libplacebo to BT.709, dumped for the golden clips. | CB1 worktree tool only | dumps in `~/cb1-sdr-ref`; item 4's compare tool against them | the build host is busy with the release now; libplacebo renders 4:4:4 from a float reconstruction, so the difference includes the reconstruction's (as it did for HDR10: mean a code and a half of 12 bits) | 3 |
| 9 | **Kodi's shader default.** New profiles get Hable, not "off", for HDR10 on a display without HDR. A general patch (9909). | `xbmc/cores/VideoSettings.cpp` or `MediaSettings.cpp` | a fresh profile's `guisettings.xml`; an HDR10 title on an SDR mode | whether existing YBLOD installs have 0 saved (then a one-time migration, or leave the user's value) | 0.5 |
| 10 | **HDR10, HDR10+ and HLG through the engine** (decision 8). HDR10+: the existing `dvvk_hdr10plus_to_dovi` route, allowed for the SDR mode (today Dolby Vision output only). HDR10: a sibling that writes the identity composer and L6, with no L1 (the map then uses static metadata, as libplacebo does). HLG: a source-transfer switch in the map (the HLG inverse OETF and OOTF are a function of the source R'G'B', so they fit the 3D LUT). Later: L1 from the engine's measured statistics, with libplacebo's smoothing and scene detection. | `yblod-engine/src` (a small `yblod_hdr10_dovi.c`), `dv_map.c`, `dv_map.glsl`; Kodi `DVDVideoCodecFFmpeg.cpp` (the `m_dvHDR10Plus` machinery generalised), `DVHDR10PlusToDovi.h`, eligibility | the map of an HDR10 title equals item 1's map of the same pixels as Profile 8.1; 0.3's HDR10 patches through `dvvk-map-test` | measured-statistics L1 can pump if smoothed badly; N150 cost at 60 fps (section 6) | 7 |
| 11 | **Documents.** `OUTPUT-MODES.md` (the mode, the settings, what plays where), `VALIDATION.md`, `KODI-PATCHES.md`, release notes. | docs | review | none | 1 |

Phase 1 (Dolby Vision to SDR on 2160p modes): items 1 to 6, 8, 9, 11, about 26 days. Item 7 adds 7, item 10 adds 7.

## 5. What "correct" means, and how it is shown

There is no reference SDR rendering to match byte for byte. CB1 has no SDR path ("Standard HDR10/SDR playback remains owned by the player", `CB1/docs/CIRCUITS.md`; checked in `/Users/bryanhoban/Projects/libreelec-x86-DV-vk`, branch `feature/yblod-vulkan-engine`, `3624692dc1`); its only SDR knowledge is the Dolby target table (target display 1 = 100 cd/m2, BT.709, BT.1886) and the note that the six-vector trims are for SDR. Dolby's own SDR rendering is not public beyond the trim controls guide and SMPTE ST 2094-10's curve. So the reference is defined, in three tiers:

1. **Exact (the engine against itself).** The engine's SDR frame against the CPU's double-precision map of the same Master Reference frame (`dvvk-map-test`), every sample: at most one output code with dither off; with dither on, the CPU map plus the same pattern. This is the HDR10 mode's check, unchanged in kind. The reconstruction under it stays byte-exact (golden.sh).
2. **Independent (libplacebo itself).** The same frames through real libplacebo with the same recipe and target (item 8), as CB1's Reference Basic was for HDR10. Proposed tolerance, to be set after the first run: mean at most 0.25 of an 8-bit code and 1 dE ITP, no pixel over 3 dE ITP outside the first and last picture rows.
3. **Sanity (no GPU).** 0.3's grey ramps and patches through the CPU map: monotonic, white reached only at the source's peak, no channel outside the target's range, black at code 0 (16 in limited range).

Test set, all without a TV: 1917 (P7 FEL), Gemini Man (P7 MEL, 60p), 28 Years Later (P8.1), the Dolby Vision Landscape demo (P5, 4000 cd/m2, `--start 34.6`), each at white 100 and 203; for item 10 the base layer of 28 Years Later as HDR10, and an HDR10+ and an HLG clip (neither is in the set today). A Profile 8.4 clip is missing from the set.

What the build host's GPU can validate: tiers 1 to 3, cost on a UHD 770, the Kodi compile check. What the N150 adds: cost at the low end. What needs a display: section 7.

An SDR-only TV is not needed for the display test. Every HDR TV shows an SDR signal, and the HDFury Arcana can present an EDID without HDR and Dolby blocks, which is what the automatic fallback has to see.

## 6. Cost, from what is measured

The HDR10 map's cost over the tunnel is the nearest measurement (big-fella `docs/hdr10-output.md`, N150, GPU ms per frame, whole frame): Gemini Man 60p 11.74 to 14.87; 1917 24p 17.24 to 18.66; 28 Years Later P8.1 24p 7.94 to 10.56. On the Ryzen: 7.18 to 7.85, 14.70 to 14.90, 5.07 to 5.99. The SDR map is the same lookup with RGB words; expect the same 1.5 to 3 ms on the N150, less the cheaper GUI blend, plus the gamut LUT sample in the exact pass. So Dolby Vision to SDR at 24 or 30 fps fits the N150 (under 19 ms of 41.7). At 60 fps and 3840x2160 the N150 has under 2 ms to spare, as in HDR10 mode. Plain HDR10 through the engine is the Profile 8.1 case: about 10.6 ms at 4K on the N150, fine at 24 to 30 fps, marginal at 60; on a 1080p canvas (item 7) the pack writes a quarter of the pixels. The cost of Kodi's own shader on the N150 is not in any note, so the engine's cost for HDR10 cannot be compared with it yet. The LUT bake's own cost per L1 change is not recorded either; a title whose L1 changes every picture would bake every picture.

## 7. Not established without hardware, and other risks

Not established:

- That a new YBLOD profile's tone mapping default is really "off" (it is by the code); and what existing installs have saved.
- The picture itself on an SDR TV and on a projector: levels (full or limited range as Kodi's setting says, the kernel's `Broadcast RGB` default on a CTA mode), banding at 8 bits through the pipe's range compression, the gamma choice.
- That the bridge's flips are accepted without the tunnel property on every route (they are ordinary KMS; nothing in the patches refuses them): native HDMI, the DP-to-HDMI converters, the NUC7's LSPCON, amdgpu.
- The plane-scaler interim for 1080p (section 3).
- Kodi's shader cost and the bake cost on the N150 (section 6); the share of marked cells in SDR.
- `mediump` precision of Kodi's shader on these drivers.
- Whether the golden titles carry 100-nit L2/L8 trims (decision 6 does not depend on it).
- Projector EDIDs: none was examined. Detection is `IsHDRDisplay()`; a projector that advertises HDR10 and handles it badly is the case for selecting "Convert to SDR" by hand (and `winsystem.ishdrdisplay` off for HDR10 sources).

Risks:

- **Two looks.** Dolby Vision through the engine and HDR10 through Kodi's shader will not match until item 10. Say so in the help text.
- **GUI order.** The SDR mode blends the GUI after the map, the other modes before it: one more pack variant to keep exact, and the GUI caches must not mix the two.
- **Canvas change (item 7)** touches the engine widely. Golden hashes at 3840x2160 are the guard; do it as its own change.
- **Mode switching.** In SDR the whitelist may pick a mode smaller than the canvas the engine was created with; the engine then has to be recreated at the new size, or the mode pinned as the tunnel modes are.
- **Trims off** means a title graded with a strong 100-nit trim will not look like Dolby's SDR. That is the accepted position for HDR10; it is more visible in SDR.
- **Expectations.** This is not Dolby's content mapping and must not be called Dolby Vision in the menu: "Convert to SDR".

## Sources

- Code: this repository at `8b5608259b`; Kodi `e6192109` with the fork's patches; CB1 at `3624692dc1`; big-fella `docs/hdr10-output.md`.
- Kodi upstream commit `0bb1747a9a4b` (tone map default), `xbmc/cores/VideoSettings.cpp` on master, Omega and Nexus.
- FFmpeg `libavfilter/vf_tonemap_vaapi.c`, `vf_vpp_amf.c` (master); libva `va/va_vpp.h`; intel/media-driver `README.md` and `docs/media_features.md`; GPUOpen AMF `README.md` and `amf/public/include/components/VideoConverter.h`. All read on 2026-11-11.
- Standards named by the code used: ITU-R BT.2390 (EETF), BT.2446 method A, BT.2408 (203 cd/m2 reference white), BT.1886, BT.2124 (dE ITP), SMPTE ST 2094-10; libplacebo `tone_mapping.c`, `gamut_mapping.c`, `colorspace.c` as vendored.
