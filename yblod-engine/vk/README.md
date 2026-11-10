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
(packages/graphics/yblod-engine-vk; Kodi patches yblod-23, -25 and -27). The OpenCL engine
stays installed as the fallback.

**CB1 Master Reference's processing** (`dvvk_plan_in.cb1_contract`): the
engine can also render a picture exactly as CroqueMr's CB1 Master Reference
does (libreelec-x86-DV): the stream's chroma siting also with an EL, 4:2:0
reshaping, no chroma phase pre-filter, the ETSI GS CCM 001 Annex B EL and
4:2:2 filters, and CB1's metadata serializer (block order, L5 always, packet
id on a payload change). Checked byte for byte against CB1's own code with
`dvvk-mr-compare` in that tree (P7 FEL, P7 MEL, P8.1, letterboxed P8.1, P5;
Intel and AMD). Kodi's adapter (patch yblod-25) asks for it for unscaled
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

Test tools (`tools/`, not in the image): `dvvk-bench` (the engine alone,
headless; `--flip` for Kodi's GUI framebuffer, `--el-scaler`, `--output hdr10|hdr10plus`) with `golden.sh` and
`golden.sha256` (the byte-for-byte oracle; runs in the image's root, busybox
included), `dvvk-routes`, `dvvk-fence`, `vkprobe`, `dvvk-prepare`, and the
`dvvk-interop` binary in the crate. `cargo test` covers plan.c's packets, CB1's
order and ids, CM4, pack selection, damage and the ABI layouts (CPU only).
The OpenCL comparison (`dvvk-compare`, `regress.sh`) went with big-fella's
OpenCL engine; git history has it.
