History of yblod-engine/vk/README.md, moved out of it on 2026-11-18: the
engine's import from big-fella's dv-engine-vk (2026-10-27) and the sync of
2026-11-01, with what was checked then. SYNC-*.md next to this file record
the imports in full. The live document is [../README.md](../README.md).

<!-- yblod-engine/vk/README.md, lines 10-36 before 2026-11-18 -->

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
