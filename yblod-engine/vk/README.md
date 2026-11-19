# yblod-engine/vk: the source-tunnel engine on Vulkan compute

`libdv_engine_vk.so.1`, a Rust crate (`ash`, GLSL compute shaders compiled to
SPIR-V by `glslc`): YBLOD's Dolby Vision engine, the only one since 0.4.0.
It reconstructs each picture from the decoded VAAPI surfaces and makes the
output: the source tunnel (the pack, letterbox, metadata packets and the GUI
overlay) or one of the conversions below. The tables and metadata come from
yblod's own host C in `../src`, compiled in by `build.rs`
(`YBLOD_ENGINE_SRC`). The C API is `include/dv_engine_vk.h`.
`packages/graphics/yblod-engine-vk` builds and installs it; Kodi's adapter
(patch kodi-9956-dv-vulkan-engine-adapter) dlopens it, and if it is missing
or does not start, Dolby Vision titles play as plain base-layer video.

Imported on 2026-10-27 from big-fella's `dv-engine-vk` at 40ef696, which had
been ported there from YBLOD's OpenCL engine, and synced from it on
2026-11-01 (c727cc74e9) and 2026-11-08 (the HDR10 output); the import and
the syncs are in [history/](history/README.md). Two things only Kodi uses:
- `dvvk_set_overlay_ex` with `DVVK_OVERLAY_FLIP_Y`: Kodi's GUI framebuffer
  (rows bottom first) read in place, also by CB1's tile occupancy scan;
- `DVVK_SURFACE_CHECK=1`: each decoded surface exported every frame and
  compared. Kodi's adapter resets the engine when either layer's surfaces
  come from another pool, so runtime.env ships it 0.

**CB1 Master Reference's processing** (`dvvk_plan_in.cb1_contract`): the
engine can also render a picture exactly as CroqueMr's CB1 Master Reference
does (libreelec-CB1): the stream's chroma siting also with an EL, 4:2:0
reshaping, no chroma phase pre-filter, the ETSI GS CCM 001 Annex B EL and
4:2:2 filters, and CB1's metadata serializer (block order, an L5 where CB1
sends one, packet id on a payload change). Checked byte for byte against CB1's own code with
`dvvk-mr-compare` in that tree (P7 FEL, P7 MEL, P8.1, letterboxed P8.1, P5;
Intel and AMD). Kodi's adapter (patch kodi-9956) asks for it for unscaled
pictures with Enhancement layer upscaling Annex B (`DV_EL_SCALER=annexb`,
the default); scaled pictures, and Bilinear, stay yblod's own. The code forks on `cb1_contract` in
`yblod/plan.c` and on `chroma_filter` / `ANNEXB` in `shaders/pack.comp`.

**YBLOD 0.4.0** (ABI 3, soname still `.so.1`; the layouts are unchanged):
- *EL upsampling: Annex B or bilinear.* `dvvk_plan_in.el_scaler` is
  `DVVK_EL_ANNEXB` (1) or `DVVK_EL_BILINEAR` (2); nearest neighbour (0) is
  gone and refused (`DV_INVALID`). Bilinear is 2-tap linear interpolation at
  Annex B's sample phases (`shaders/common/dv_common.glsl` `el_bilinear_*`,
  the push constant `el_method` in every FEL shader and the pack); its CPU
  reference is `dv_bilinear_scale2x` in `../src/pixel_spatial.c`. Bilinear
  FEL takes the fused route (`fel_chroma` + the pack's luma), Annex B stays
  staged; `cb1_contract` is always Annex B. golden.sh: every Annex B hash
  unchanged, the former nearest runs now bilinear (`fel-bl*`, recorded on
  the build host's UHD 770; DVVK_VERIFY fused = staged).
- *Dolby Vision -> HDR10+.* `dvvk_set_output_mode(DVVK_OUTPUT_HDR10PLUS)`:
  the HDR10 output's reconstruction without its tone curve, the pack
  measuring the active film area before the overlay (`STATS`: 16-nit maxRGB
  histogram, channel maxima, average maxRGB), read back without a wait, and
  `dvvk_hdr10plus_packet(ticket)` building the 31-byte HDR10+ InfoFrame with
  CroqueMr's CB1 metadata code (`../src/cb1_dv_hdr10plus.c` and friends,
  ported at a pinned commit). Statistics checked against the CPU reference
  (`dvvk-hdr10-compare --stats` on the dumps, `DVVK_HDR10PLUS_TRACE=1`).
- *HDR10+ -> Dolby Vision.* `dvvk_hdr10plus_to_dovi`: CB1's
  `cb1_hdr10plus_dovi.c` as Profile 8.1 metadata (identity composer, L1, L6)
  for `dvvk_submit`.
- `cargo test` runs CB1's HDR10+ tests, ported unchanged (`yblod/tests`).

**After 0.5.0: SDR output and a run-time canvas** (ABI 3 still; new optional
symbols and enum values only, the layouts and the soname unchanged):
- *SDR output.* `dvvk_set_output_mode(DVVK_OUTPUT_SDR)`: the HDR10 output's
  recipe to an SDR display (`peak_nits` its white, 203 by default; BT.709,
  BT.1886 or `DVVK_SDR_GAMMA22`, `DVVK_SDR_LIMITED`), 8-bit R'G'B' in
  XRGB8888. `yblod/dv_map.c` plans it with the vendored libplacebo (spline
  on L1, `pl_gamut_map_perceptual` from L9's primaries as a 48x32x256 LUT
  the shaders sample as a 3D texture); `map_bake.comp` bakes R'G'B' codes
  into a 129x65x65 LUT over the reconstructed codes themselves (luma up to
  the scene's peak, chroma 512 codes either side of neutral, 1024 for HLG:
  `include/dvvk_map.h`) and marks the cells where the LUT is off by more
  than 0.35 of a code at 19 points, and those of the box's faces; the pack
  interpolates each pixel's chroma, reads the LUT, and hands the samples
  whose lookup has alpha 0 (the marked cells and those they enclose) to
  `map_fixup.comp` (a list entry a pair, with the next pair's chroma as a
  7-bit difference). Its PQ curves are written to keep a float's precision
  (`map_pq_eotf_sdr`): a display channel near 0 is a small difference, and
  the textbook form put it up to five codes from the CPU's double with a
  2.2 power. A source's R'G'B' above 1 is kept (HLG's as it is, PQ's to
  1.5), as libplacebo keeps it. Dither: a fixed
  64x64 blue-noise table (`yblod/dither_blue64.h`, made by
  `tools/dither-table.c` from libplacebo's generator, checked in because
  the generator uses `rand()`). The overlay is the `dvvk_set_overlay`
  buffer alone, blended after the map (`OVERLAY` 4); a frame with another
  kind of overlay is refused. `dvvk_output_modes()` says whether the
  library has the mode.
- *Canvas.* `dvvk_create_canvas(drm_fd, va, width, height, &engine)`: the
  output buffers' size, both sides multiples of 4, 64 to 4096 (`dvvk_create`
  is 3840x2160). Every mode runs at any canvas; the tunnel is only defined
  at 3840x2160.
- *Sources without Dolby Vision* (SDR output): `dvvk_hdr10_to_dovi` writes
  an HDR10 or HLG video's metadata (an identity composer, L6, L9, no L1;
  `../src/yblod_hdr10plus.c`), `DVVK_SDR_HLG` says the codes are HLG
  (libplacebo's HLG linearisation; its own pipelines, the shaders' `MAP_SDR`
  2, so PQ pipelines keep their bytes), and `dvvk_hdr10plus_to_dovi` serves
  HDR10+ as before (with the mastering primaries when
  `dvvk_hdr10_static.primaries` names them).
- Checks: `tools/sdr-check.sh` with `tools/sdr.sha256` (every sample within
  one code of `dvvk-map-test`'s CPU map, and hashes for the GPU named in the
  file: UHD 770, Mesa 26.2.6), `tools/sdr-oracle.c` (libplacebo itself; not
  built with the engine), `dvvk-sdr-compare`, `tools/sdr-eval` (the research
  harness's ramps and patches). golden.sh's 102 + 18 hashes and the HDR10
  dumps are unchanged by all of it.
  [OUTPUT-MODES.md](../docs/intel-dv/OUTPUT-MODES.md#convert-to-sdr) has the
  results and the cost.

**0.5.1 fixes** (ABI 3, layouts unchanged):
- *HDR10+ from stock FFmpeg.* `dvvk_hdr10plus_to_dovi` reads an
  `itu_t_t35_country_code` of 0 as 0xB5: stock FFmpeg makes the side data
  only from a T.35 header it checked to be ST 2094-40's but leaves the field
  0, CB1's FFmpeg writes 0xB5, and CB1's `cb1_hdr10plus_dovi_describe`
  (unchanged) wants 0xB5. Before, every real HDR10+ picture was refused.
- *Single-layer MMR under the CB1 contract.* A picture with MMR reshaping
  and no EL (Profile 8.x, a Profile 7 base layer alone) under `cb1_contract`
  takes the 4:2:0 P010 piecewise kernel (`piecewise[3]`, CB1's contract 1
  luma guide), which a guard from the OpenCL port refused (-2) at 4K.
  dvvk-mr-compare: CB1's Master Reference byte for byte.

**CB1 at b5149a09d7** (ABI 3, layouts unchanged):
- *No L5 invented for an RPU without one* (CB1 4b80e75da2) under
  `cb1_contract`: the serializer appended a zero (full-raster) L5 to such
  an RPU, which makes a display (an LG C1, a Hisense) apply the L2 lift to
  the letterbox bars. Now the placement adds an L5 only for the borders it
  makes, and none while an overlay shows (CB1 places with zero margins
  then). An RPU's own L5, and its zeroing under an overlay, are unchanged.
  yblod's own serializer already added an L5 only for placement borders.
  The fixtures and golden.sh's pictures all carry an L5: its hashes are
  unchanged.
- *HDR10+ application version 1's luminance* (CB1 9b76275086): its
  DistributionY99 (the 5 % entry) is the scene's largest 99.99th
  percentile of BT.2020 luminance and DistributionY100nit (the 10 % entry)
  the scene's mean share of pixels at or below 100 nits, where 0 and 255
  were sent; `targeted_system_display_maximum_luminance` is 0 when no curve
  is sent (both versions). `STATS` also counts a 16-nit luminance histogram
  and the pixels at or below 100 nits (a 519-word record). The engine keeps
  CB1's scene (`cb1_hdr10plus_analysis_stage_scene` / `_commit_scene`):
  every finished HDR10+ frame's statistics in ticket order, a new scene on
  the RPU's scene refresh, a missing frame or `dvvk_reset`; a packet made
  commits it. The maxRGB statistics are unchanged (DVVK_HDR10PLUS_TRACE on
  44 frames before and after); the luminance fields the packets carry equal
  `dvvk-hdr10-compare --stats` on the dumps.
- *Every vendored CB1 file at b5149a09d7* (`../SOURCES.md`), with CB1's
  tests: `dvbridge_policy`'s SDR and player-led modes and fields,
  `dvbridge_creative`'s resolver choosing among CM4 anchors by display
  gamut (`cb1_display_primaries`, ported alone from `cb1_hdr10_expert`) and
  its `analysis_valid`, `cb1_cmv40.h`'s status in the plan, and
  `dvbridge_dv_is_mel` in `dvbridge_metadata_bounds.h`. Compiled in, not
  used: the HDR10+ policy has no player-led display.

**After 0.5.1: CroqueMr's CB1 SDR targets** (ABI 3 still; new flag values,
`dvvk_output_mode.reserved[0]` and the optional `dvvk_sdr_flags`; layouts
and soname unchanged). The SDR output takes every display CB1's SDR
rendering offers (`CB1/src/dvbridge_policy.c dvbridge_sdr_target`,
`dvbridge_render.c sdr_container`):
- *A pure power* (`DVVK_SDR_POWER`, the gamma in thousandths in
  `reserved[DVVK_SDR_GAMMA_WORD]`, 1.8 to 2.8): black-scaled like
  `DVVK_SDR_GAMMA22` (2.2 gives that flag's bytes), as libplacebo's GAMMA24
  and CB1's custom gamma (GAMMA24 then the signal to the power 2.4 / gamma).
- *The black as given* (`DVVK_SDR_BLACK`): `min_nits` 0 to 5 cd/m2 and
  below the white, 0 a true zero (libplacebo's `PL_COLOR_HDR_BLACK`, as
  CB1); without the flag 0 still means white / 1000.
- *White from 20 cd/m2* (was 40; to 1000 as before).
- *BT.2020* (`DVVK_SDR_BT2020`): the display's primaries for the gamut
  mapping and the output matrix; `dvvk_output_signal` names them for the link's colorimetry; the
  overlay's sRGB colours are converted through the display's transfer
  (`map_sdr_layer_bt2020`, its greys keep their codes).
- Presets (`dvvk_output_mode {mode, flags, peak_nits, min_nits, reserved}`):
  Reference `{SDR, POWER|BLACK, 100, 0, {2400}}`, Bright room
  `{SDR, POWER|BLACK, 200, 0, {2200}}`, Custom / projector
  `{SDR, POWER|BLACK, 20..500, 0..5, {gamma x 1000}}`, each `| BT2020` for
  CB1's BT.2020 gamut. An older library refuses these modes (-2) rather
  than approximating them; a reserved word without its flag is refused too.
- With a black above zero a pure power's slope at the black has no bound,
  and the sampler's 8-bit weights on libplacebo's gamut LUT put samples two
  codes from the CPU map there (gamma 1.8, 5 of 20 cd/m2): such modes read
  that LUT with exact weights (`DVVK_MAP_GAMUT_EXACT`, eight texels). The
  earlier displays keep the sampler and their bytes.
- Checks: golden, the HDR10 dumps, the 78 earlier `sdr.sha256` hashes and
  `cpu-baseline.txt` unchanged; 14 new `sdr-check.sh` pictures (each
  preset, gammas 1.8, 2.6 and 2.8, blacks 0.05 and 5, BT.2020 with the GUI
  and from HLG) within one code of `dvvk-map-test`. Accuracy and cost:
  [OUTPUT-MODES.md](../docs/intel-dv/OUTPUT-MODES.md#cb1s-sdr-targets).

**After 0.5.1: the upscaler** (ABI 3 still: a new optional symbol and enum,
the layouts and the soname unchanged). CroqueMr's CB1 lets Dolby Vision
pictures be enlarged with AMD FidelityFX Super Resolution 1; so does this
engine now, in its own way: FSR runs on the reconstructed luma inside the
engine, where CB1 runs it in Kodi's GL renderer on the reshaped Y'CbCr.
- *API.* `dvvk_set_scaler(engine, method)`: `DVVK_SCALER_BILINEAR` (0, the
  default, the pack's own interpolation), `DVVK_SCALER_FSR1_EASU` (1),
  `DVVK_SCALER_FSR1_RCAS` (2: EASU, then RCAS sharpening), from the next
  frame, in every output mode (tunnel, HDR10, HDR10+, SDR: they map what the
  pack made). -2 for a method the library doesn't have (the choice stays as
  it was), -1 for NULL; a library without the symbol is bilinear. Only an
  enlargement takes it (neither side smaller, one larger: `src/scaler.rs`
  `effective`). Reductions and unscaled pictures (so also CB1's contract) are
  never touched. dvvk-bench: `--scaler bilinear|easu|rcas|N`, `--scaler-from N`.
- *Domain.* Luma only, as mpv's FSR port does it (a luma hook): the
  reconstructed 12-bit luma codes / 4095, the stream's PQ Y' (FSR wants a
  perceptual 0..1 signal), each sample a grey pixel, so AMD's "luma times 2"
  is 2 Y. Chroma stays the pack's bilinear 4:2:0 -> 4:2:2.
- *Passes.* A frame FSR enlarges takes the staged reconstruction (the
  bilinear FEL leaves its fused pack for it; the staged kernels give the
  same codes). Then `shaders/fsr1_easu.comp` runs EASU from the staged luma
  plane to a plane of the destination's size, as codes x 16: 4 fraction
  bits, because RCAS multiplies a rounding error up to about 2x. It works in
  16x16 workgroups, with the source texels in shared memory, over the film's
  part of the destination and one pixel beyond. The pack (`SCALER` 1, 2;
  constant 0 is today's pipeline) reads that luma instead of interpolating
  it. With RCAS it sharpens the 5-tap cross there, so there is no second
  pass and no second image. The plane (2 bytes a canvas pixel), the EASU
  pipeline and the FSR pack variants are made on the first enlarged picture
  that uses them: a player that never selects FSR has none of it. Each FSR
  variant costs about 80 ms the first time it is used, 5 to 15 ms once the
  pipeline cache has it.
- *Edges.* EASU's taps clamp at the picture's edges, as AMD's sampler does.
  RCAS's cross clamps at the destination's. A letterboxed source is enlarged
  over its reconstructed bars (the row window's 12-row margin covers EASU's
  two rows beyond the film), then the active area blacks them out, as with
  bilinear. A resized destination is a multiple of 4 in both sides (yblod's
  geometry). The pass takes any size, any ratio and any position (checked
  at 3836x2156 from 4,2 and 4096x4096 from 3840x2160).
- *From AMD's code* (`shaders/common/fsr1.glsl`, written from ffx_fsr1.h
  v1.20210629, MIT, `LICENSES/MIT-AMD-FidelityFX-FSR.txt`): the 32-bit EASU
  and RCAS, the bit-pattern approximations bit for bit, RCAS with
  `FSR_RCAS_DENOISE` at one stop (0.5: CB1's strength, CB1's noise limit). A
  limiter's 0/0 (a ring all at 0 or 1) takes the other operand, as AMD's HLSL
  `max()` does with the NaN. One change: RCAS's resolve divides exactly.
  AMD's APrxMedRcpF1 there is up to 0.32 % low, even unsharpened. That is
  under a code of 8-bit sRGB, but up to 13 of these 12-bit PQ codes: a flat
  area's level moving with the noise term. CB1's shader divides exactly too.
- *Accuracy.* `tools/dvvk-scaler-compare.c` is a CPU reference: EASU and
  RCAS in double, with what AMD defines in float kept float (FsrEasuCon's
  constants, the position's fused mad, the approximations). It compares a
  tunnel picture's luma with the reference made from the same picture
  unscaled. Pixels whose taps reach a source's bars are left out, because
  the unscaled picture has them black. Where EASU's direction test is within
  1e-5 of its 1/32768 threshold, float and double may branch apart; either
  result is FSR's, the closer one is taken, and such pixels are counted
  (0 to 235 a picture). `tools/scaler-check.sh` (40 pictures: 1080p Profile
  8.1 made with libx265 from two clips, one of them letterboxed, the odd
  destination; 1917 FEL with both EL scalers and Gemini Man MEL into a
  4096x4096 canvas) found:
  - every code within one of the reference;
  - EASU: 97.0-97.3 % equal, the rest +1 (the 1/16-code plane rounds twice);
    at most 0.53 code from the unrounded reference;
  - EASU + RCAS: 97.8-98.0 % equal, about 1.0-1.1 % each at -1 and +1; at
    most 0.56 code.
  The script also checks that `--scaler bilinear` gives the bytes of a run
  without the call, and that those are the engine's from before the
  scaler. Switching to FSR mid-stream gives FSR's bytes from the start:
  the damage key holds the scaler, so the four output buffers are rewritten
  whole. The FLIP_Y twin gives its twin's bytes, and an unknown method is
  refused. Hashes are in `tools/scaler.sha256` (UHD 770, Mesa 26.2.6;
  strict when vulkaninfo names those, `SCALER_STRICT` overrides):
  - tunnel EASU and RCAS;
  - HDR10, HDR10+ and SDR (also with SDR's layer);
  - the fused shell, the prepared overlay (`DVVK_OVERLAY_PREPARE=1`) and
    the rect damage.
  Run it on a box with the GPU as `WORK=<work dir> sh tools/scaler-check.sh
  check p81-3840x1744-l5full.mkv 28yl-p81.mkv 1917-fel.mkv gemini-mel.mkv`
  (the reference clips; `GOLDEN` defaults to `tools/scaler.sha256`).
- *Not used with FSR.* `DVVK_VERIFY` skips FSR frames: its reference pack
  is bilinear, and their reconstruction is staged already. `dvvk-prepare`
  leaves the FSR pipelines to first use: only a player that selects FSR
  needs them, and preparing them would add them to every boot.
- *Cost* (UHD 770, the tunnel, 1080p Profile 8.1 full screen into
  3840x2160, the whole frame active; dvvk-bench `DVVK_PROFILE=1`, GPU ms a
  frame over 120 frames, three runs each; the pack's figure includes the
  EASU pass):

  | | bilinear, before | bilinear, after | EASU | EASU + RCAS |
  |---|---|---|---|---|
  | flat out (`--rate 0`) | 4.99, 5.00, 5.29 | 4.99, 5.08, 5.18 | 12.58-12.61 | 13.94-13.96 |
  | 23.976 Hz (the GPU downclocks) | 14.7, 15.2, 15.7 | 14.6, 15.7, 16.1 | 17.8-18.3 | 17.4-18.8 |

  The bilinear pack is unchanged: same pipelines, same bytes, same time.
  EASU costs about 7.6 ms a 4K frame at full clock on this 32-EU GPU (its
  arithmetic, near this GPU's FP32 rate; AMD's FP16 path would lose the
  one-code accuracy). RCAS costs about 1.35 ms more. At playback's 23.976
  Hz that is +3 ms of a 41.7 ms frame.

**After 0.5.1: CB1's display-targeted outputs** (ABI 3 still; a new mode,
flag values, `dvvk_output_mode`'s fields and `reserved[0]`, and the optional
`dvvk_set_display_primaries`, `dvvk_target_flags` and
`dvvk_lldv_display_from_vsvdb`; layouts and soname unchanged). CroqueMr's
CB1 maps Dolby Vision to a stated display with one recipe, his "Expert"
(`CB1/src/cb1_hdr10_expert.c`), behind two front ends; the engine has both:
- *Player-led Dolby Vision* (`DVVK_OUTPUT_LLDV`, CB1's "LLDV Reference -
  Native", `CB1-DVLLDV`): the picture mapped to the TV's own peak, black and
  primaries (`peak_nits`, `min_nits`, `dvvk_set_display_primaries` with the
  VSVDB's version; without them `reserved[DVVK_TARGET_GAMUT_WORD]`'s gamut,
  BT.2020 by default) and sent as BT.2020 PQ Y'CbCr 4:2:2 limited range in
  the HDR10 output's 12-bit carrier, 12 useful bits or 10
  (`DVVK_LLDV_10BIT`). The TV shows it without mapping it again: the player
  signals the Dolby VSIF with the low-latency bit, AVI 4:2:2 BT.2020
  limited, and no HDR static metadata (this tree's kernel:
  `DVBRIDGE_TUNNEL_FORMAT` "lldv"). `dvvk_output_signal`: mode 4, eotf 2,
  the display's primaries and luminance, `reserved[0]` the useful bits.
- *HDR10 Rendering Reference* (`DVVK_OUTPUT_HDR10 | DVVK_HDR10_TARGET`,
  CB1's "LLDV Reference - HDR10 Output", `CB1-DVHDR10X`): the same map to a
  display the user states (peak 50 to 10000 cd/m2, black 0 to 0.5: CB1's
  OLED 0, LCD 0.005, projector 0.05; gamut BT.709, P3-D65 by default, or
  BT.2020), sent as the HDR10 output is; `dvvk_output_signal` the virtual
  target's static metadata (its primaries, max and min luminance, MaxCLL
  and MaxFALL 0). A flag of the HDR10 mode, not a mode: carrier, signalling
  and overlay are the HDR10 output's, only the map's target differs; plain
  `DVVK_OUTPUT_HDR10` (flags 0, peaks 0) keeps its bytes.
- *A display's target from its EDID*: `dvvk_lldv_display_from_vsvdb` turns
  a raw Dolby Vision VSVDB (from its CTA header byte on) into peak, black,
  primaries fitted inside BT.2020, version and capabilities (TV-led Dolby
  Vision, 12-bit 4:2:2, 4:4:4 depths), or a status saying why there is none
  (no low-latency 4:2:2, invalid primaries, outside BT.2020, ...): CB1's
  Kodi `ReadLldvDisplay` and `dvbridge_parse_edid`, ported to C for one block
  (`yblod/lldv_vsvdb.c`), for Kodi and mpv alike.

The map: `yblod/dv_map.c` turns the mode into CB1's policy
(`dvbridge_policy_validate` decides what is a display), runs his plan
vendored unchanged (`cb1_player_led_prepare` / `cb1_hdr10_expert_prepare`:
libplacebo's ST 2094-10 curve when the scene's L1 maximum is above the
peak, else a clip, over PQ(black)..PQ(peak), 1024 or 4096 entries; L1 with
L6 or the source peak as fallback; the L2 anchors' slope, offset and power
bent into the curve by his 9918 libplacebo patch's fill, `yblod/placebo/
cb1_expert_tone.c`; L8's CM4.0 controls through `player_led_trims`, LLDV
only), then makes the decisions his shaders make: `pl_shader_color_map_ex`
with an explicit curve (the fast path, or IPT, the curve on I with the hull
desaturation, libplacebo's perceptual gamut map into the display's
primaries), the EDID basis, his CM4 shader (`dvbridge_creative_cm4_shader`'s
coefficients), `cb1_hdr10_expert_trim`'s chroma, saturation and cap; then
the tail: `dvbridge_pack_player_led_422`'s matrix and scale (LLDV), or
`reference_output`'s BT.2020 PQ adapter and the Expert ceiling (HDR10). The
shaders (`shaders/common/dv_map.glsl` `map_expert`, under the constant
`MAP_EXPERT`, so the other outputs' pipelines compile from their old code)
compute the same in float, CB1's CM4 GLSL as he wrote it; the 3D LUT is
HDR10's cube, checked at 19 points a cell, and an LLDV sample in a marked
cell is computed in the pack (its pair's chroma needs the neighbour's
sample, which `map_fixup`'s list doesn't carry). LLDV decodes as CB1's
player-led path does (codes / 4096, the RPU's offsets as given, no clamp at
1: the cube's top faces are marked); the HDR10 target as the HDR10 output.
LLDV's pack: each pixel its pair's chroma, the overlay (the
`dvvk_set_overlay` buffer alone, as for SDR) blended after the map in the
display's linear light as `player_led_gui` does (Kodi's sRGB LUT, BT.709 to
the display, 203 cd/m2 white; the texel as it is, which is premultiplied in
Kodi's GUI buffer: CB1's player-led code, unlike his tunnel blend, doesn't
divide by alpha, and neither does this), BT.2020 PQ, the pair's chroma the
1-2-1 mean at its even pixel (left edge replicated), the codes on the
carrier's grid. Black outside the active area (L5) in both, as CB1 masks
it; an HDR10 target's overlay in the bars, blended before the map as the
HDR10 output's, keeps its colour.

Not done: CB1's optional CM2.9 -> CM4.0 append and L2 removal for
player-led output (`player_led_options`, `cb1_cmv40.c`, not ported): an
LLDV frame whose `dm_options` asks for them is refused (-2). The engine
doesn't prepare the new pipelines in `dvvk-prepare`; the first frame of
each output compiles them (about 0.3 s, then cached).

Checks (UHD 770, Mesa 26.2.6): `tools/target-check.sh` with
`tools/target.sha256` (as `sdr-check.sh`: each picture against
`dvvk-map-test`'s double-precision map of the same reconstructed picture,
`--output lldv`, `--target`, `--peak`, `--black`, `--gamut`, `--primaries`,
`--edid-version`, `--bits`, and its hash for the GPU the file names);
`tools/dvvk-lldv-oracle.c` (CB1's own AVX2 pack, `tools/cb1/cb1_lldv_cpu.c`,
on the engine's linear picture, against the engine's pack definition and the
GPU's bytes; not built by `tools.sh`); `cargo test` runs CB1's plan,
continuity, policy and trim tests and YBLOD's VSVDB tests. `dvvk-bench`
drives both outputs (`--output lldv`, `--target`, the same display options,
and `--l8-target N`, which retargets a stream's L8 trims for a test).
Accuracy and cost:
[OUTPUT-MODES.md](../docs/intel-dv/OUTPUT-MODES.md#player-led-dolby-vision-and-hdr10-rendering-reference).

Test tools (`tools/`, not in the image): `dvvk-bench` (the engine alone,
headless; `--flip` for Kodi's GUI framebuffer, `--el-scaler`, `--output hdr10|hdr10plus|sdr`,
`--canvas W,H`, `--source hdr10|hlg`; SDR's `--white`, `--black`, `--gamma22`,
`--gamma G`, `--exact-black NITS`, `--bt2020`, `--limited`; `--scaler`) with `golden.sh` and
`golden.sha256` (the byte-for-byte oracle; runs in the image's root, busybox
included), `scaler-check.sh` with `dvvk-scaler-compare` and `scaler.sha256`,
`dvvk-routes`, `dvvk-fence`, `vkprobe`, `dvvk-prepare`, and the
`dvvk-interop` binary in the crate. `cargo test` covers plan.c's packets, CB1's
order and ids, CM4, pack selection, damage and the ABI layouts (CPU only).
The OpenCL comparison (`dvvk-compare`, `regress.sh`) was removed with the
sync of 2026-11-01; git history has it.
