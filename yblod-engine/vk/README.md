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
4:2:2 filters, and CB1's metadata serializer (block order, L5 always, packet
id on a payload change). Checked byte for byte against CB1's own code with
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

Test tools (`tools/`, not in the image): `dvvk-bench` (the engine alone,
headless; `--flip` for Kodi's GUI framebuffer, `--el-scaler`, `--output hdr10|hdr10plus|sdr`,
`--canvas W,H`, `--source hdr10|hlg`) with `golden.sh` and
`golden.sha256` (the byte-for-byte oracle; runs in the image's root, busybox
included), `dvvk-routes`, `dvvk-fence`, `vkprobe`, `dvvk-prepare`, and the
`dvvk-interop` binary in the crate. `cargo test` covers plan.c's packets, CB1's
order and ids, CM4, pack selection, damage and the ABI layouts (CPU only).
The OpenCL comparison (`dvvk-compare`, `regress.sh`) went with big-fella's
OpenCL engine; git history has it.
