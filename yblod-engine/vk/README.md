# yblod-engine/vk: the source-tunnel engine on Vulkan compute

`libdv_engine_vk.so.1`, a Rust crate (`ash`, GLSL compute shaders compiled to
SPIR-V by `glslc`) that does what `libdv_source_private.so.1` does for the
source tunnel: reconstruction, the pack, letterbox, metadata packets and the
GUI overlay. The tables and metadata come from yblod's own host C in `../src`,
compiled in by `build.rs` (`YBLOD_ENGINE_SRC`), so both engines see the same
numbers. The C API is `include/dv_engine_vk.h`.

Imported from big-fella's `dv-engine-vk` at commit 40ef696 (2026-10-27), where
it was ported from this engine and checked against OpenCL on the N150 frame by
frame: every movie byte identical on every route and both EL scalers; under
the GUI, about 0.2 % of pixels differ by at most one luma or two chroma codes
(`pow` in the sRGB/PQ conversion). big-fella's docs/vulkan-engine.md has the
design and the results. Its nearest EL scaler patch is folded into `../src`.

**Synced with big-fella's 0.1.0-18** (c727cc74e9, 2026-11-01): the crate as
big-fella has it, plus what only Kodi uses:
- `dvvk_set_overlay_ex` with `DVVK_OVERLAY_FLIP_Y`: Kodi's GUI framebuffer
  (rows bottom first) read in place, also by CB1's tile occupancy scan;
- `DVVK_SURFACE_CHECK=1` (set in runtime.env): each decoded surface exported
  every frame, since Kodi's adapter doesn't reset the engine when the decoder's
  surface pool changes (big-fella's mpv does, and trusts imports by id).

From big-fella since the first sync: damage (output buffers rewritten only
where something changed), the native CB1 GUI blend under the contract (Kodi's
transfer LUTs; 8-bit unscaled overlay at 203 nits, no subtitles), tables
planned only when the composer config changes, FEL planning reusing unchanged
components, 49 instead of 66 pipelines and a pipeline cache, `dvvk_drain` /
`dvvk_reset_checked`, a panic-safe C API, `dvvk_abi_version` (ABI 2: the soname
is now `.so.1`) and CroqueMr's optional CM2.9 -> CM4.0 metadata and L2 trim
removal (`dvvk_plan_in.dm_options`; Kodi: `DV_VULKAN_CM4`, off by default).
`dvvk_overlay_changes` and `dvvk_last_gpu_ms` are gone. Checked on Ollie's UHD
770: big-fella's 90 golden hashes (recorded on the N150) identical, the
`FLIP_Y` twins identical to their upright runs, CB1's Master Reference
byte for byte on the five titles below, `cargo test`.

Kodi uses it when Settings > Player > Dolby Vision > Engine is Vulkan
(packages/graphics/yblod-engine-vk; Kodi patch kodi-9956-dv-vulkan-engine-adapter). The OpenCL engine
stays installed as the fallback.

**CB1 Master Reference's processing** (`dvvk_plan_in.cb1_contract`): the
engine can also render a picture exactly as CroqueMr's CB1 Master Reference
does (libreelec-x86-DV): the stream's chroma siting also with an EL, 4:2:0
reshaping, no chroma phase pre-filter, the ETSI GS CCM 001 Annex B EL and
4:2:2 filters, and CB1's metadata serializer (block order, an L5 where CB1
sends one, packet id on a payload change). Checked byte for byte against CB1's own code with
`dvvk-mr-compare` in that tree (P7 FEL, P7 MEL, P8.1, letterboxed P8.1, P5;
Intel and AMD). Kodi's adapter (patch kodi-9956) asks for it for unscaled
pictures when `DV_VULKAN_CB1=1` (on in runtime.env); scaled pictures, and the
OpenCL engine, stay yblod's own. The code forks on `cb1_contract` in
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
  Ollie's UHD 770; DVVK_VERIFY fused = staged).
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
  Run it as `vk.sh run 'GOLDEN=/t/vk/tools/scaler.sha256 WORK=/o/work/scaler
  sh /t/vk/tools/scaler-check.sh check /clips/p81-3840x1744-l5full.mkv
  /clips/28yl-p81.mkv /clips/1917-fel.mkv /clips/gemini-mel.mkv'`.
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

Test tools (`tools/`, not in the image): `dvvk-bench` (the engine alone,
headless; `--flip` for Kodi's GUI framebuffer, `--el-scaler`, `--output hdr10|hdr10plus|sdr`,
`--canvas W,H`, `--source hdr10|hlg`; SDR's `--white`, `--black`, `--gamma22`,
`--gamma G`, `--exact-black NITS`, `--bt2020`, `--limited`; `--scaler`) with `golden.sh` and
`golden.sha256` (the byte-for-byte oracle; runs in the image's root, busybox
included), `scaler-check.sh` with `dvvk-scaler-compare` and `scaler.sha256`,
`dvvk-routes`, `dvvk-fence`, `vkprobe`, `dvvk-prepare`, and the
`dvvk-interop` binary in the crate. `cargo test` covers plan.c's packets, CB1's
order and ids, CM4, pack selection, damage and the ABI layouts (CPU only).
The OpenCL comparison (`dvvk-compare`, `regress.sh`) went with big-fella's
OpenCL engine; git history has it.
