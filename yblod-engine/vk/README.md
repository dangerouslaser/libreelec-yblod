# yblod-engine/vk: the source-tunnel engine on Vulkan compute

`libdv_engine_vk.so.0`, a Rust crate (`ash`, GLSL compute shaders compiled to
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

Kodi uses it when Settings > Player > Dolby Vision > Engine is Vulkan
(packages/graphics/yblod-engine-vk; Kodi patch yblod-23). The OpenCL engine
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

Test tools (`tools/`): `dvvk-compare` (OpenCL vs Vulkan on decoded frames),
`dvvk-routes`, `dvvk-fence`, `vkprobe`, `regress.sh`, and the `dvvk-interop`
binary in the crate. They aren't in the image.
