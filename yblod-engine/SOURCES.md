# Source scope and references

This is a selected source export of the project's C implementation (the
host C the Vulkan engine compiles, `vk/build.rs`), not a transfer of its
development repository or all diagnostic tooling. The build lists its
translation units explicitly. The OpenCL engine (`opencl_backend.c`,
`dv_engine.c`, `dv_source_renderer.c`, the `*.cl` kernels) was removed in
YBLOD 0.4.0; the Vulkan shaders in `vk/shaders` took over their GPU work and
cite them where they port them.

Implementation references and boundaries:

- `pixel_luma.c`, `pixel_chroma_final.c`, `pixel_spatial.c`, the corresponding
  GPU kernels, and `single_reshape.c` implement reconstruction operations
  described by ETSI GS CCM 001 V1.1.1, including polynomial/MMR reshaping and
  residual composition. The enhancement-filter choice is the informative
  Annex B example, not a claim about every licensed player's active filter.
- `dv_ffmpeg_metadata.c` and `single_reshape_ffmpeg.c` consume FFmpeg's parsed
  Dolby metadata. They validate structure bounds and reject unsupported
  contracts instead of interpreting arbitrary memory as metadata. The build
  uses the matching raw-extension patches distributed elsewhere in this repo.
- `dv_cm4.c` cross-checks extension grammar against quietvoid's `dovi_tool`.
  It preserves the supplied fields while changing their representation; it
  does not implement the display's content-mapping algorithm.
- The tunnel packing (the Vulkan engine's `pack.comp`, formerly OpenCL
  `source_tunnel.cl`) packs the reconstructed samples; CPU code packetizes the
  accompanying metadata. The protocol basis is ETSI sections 6.3 and 6.4.
  The source representation and frame-bound metadata must agree. Merely
  engaging a TV's Dolby Vision mode is not an accuracy test.
- `source_overlay.c` transforms premultiplied sRGB GUI colours into the
  current source domain. The movie does not take an extra RGB round trip.
- `dv_scanout_slots.c` and the geometry helpers implement this project's
  buffer ownership and validation. Kodi carries its own copy of the scanout
  slots (`dv_scanout_slots.cpp`, Kodi patch kodi-9956); the CPU test here checks the C.

- YBLOD 0.4.0: `pixel_spatial.c` also has the bilinear EL upsampling
  (`dv_bilinear_scale2x`, the Vulkan engine's `DVVK_EL_BILINEAR` reference;
  it replaced big-fella's nearest neighbour).
- YBLOD 0.4.0, HDR10+: `cb1_hdr10plus*.c/.h`, `cb1_dv_hdr10plus.c/.h`,
  `cb1_hdr10plus_dovi.c/.h`, `dvbridge_creative.c/.h` (a subset),
  `dvbridge_policy.c/.h`, `dvbridge_metadata_bounds.h`, `mpv_dvbridge_cm4.h`
  and `cb1_trim_math.h` are CroqueMr's CB1 (github.com/CroqueMr/intel-dv-libreelec,
  GPL-2.0-or-later) at commit 9eb35aeb1146e9a6c3652b7a43225511887cdc17, each
  with its notice and that pin in its header; `LICENSES/CB1-AVDVPlus-HDR10Plus.txt`
  and `LICENSES/CB1-Hades-HDR10Plus.txt` are the notices CB1 ships for the
  HDR10+ -> Dolby Vision estimator (the GPL-2.0 text: `LICENSES/intel-dv-GPL-2.0.txt`).
  `yblod_hdr10plus.c/.h` is YBLOD's glue for the Vulkan engine
  (`vk/include/dv_engine_vk.h`: `dvvk_hdr10plus_packet`, `dvvk_hdr10plus_to_dovi`).
  The Vulkan engine compiles them (`vk/build.rs`); CB1's tests run in its
  `cargo test` (`vk/yblod/tests`).

- YBLOD 0.4.0: `pixel_spatial.c` also has the bilinear EL upsampling
  (`dv_bilinear_scale2x`, the Vulkan engine's `DVVK_EL_BILINEAR` reference;
  it replaced big-fella's nearest neighbour).
- YBLOD 0.4.0, HDR10+: `cb1_hdr10plus*.c/.h`, `cb1_dv_hdr10plus.c/.h`,
  `cb1_hdr10plus_dovi.c/.h`, `dvbridge_creative.c/.h` (a subset),
  `dvbridge_policy.c/.h`, `dvbridge_metadata_bounds.h`, `mpv_dvbridge_cm4.h`
  and `cb1_trim_math.h` are CroqueMr's CB1 (github.com/CroqueMr/intel-dv-libreelec,
  GPL-2.0-or-later) at commit 9eb35aeb1146e9a6c3652b7a43225511887cdc17, each
  with its notice and that pin in its header; `LICENSES/CB1-AVDVPlus-HDR10Plus.txt`
  and `LICENSES/CB1-Hades-HDR10Plus.txt` are the notices CB1 ships for the
  HDR10+ -> Dolby Vision estimator (the GPL-2.0 text: `LICENSES/intel-dv-GPL-2.0.txt`).
  `yblod_hdr10plus.c/.h` is YBLOD's glue for the Vulkan engine
  (`vk/include/dv_engine_vk.h`: `dvvk_hdr10plus_packet`, `dvvk_hdr10plus_to_dovi`).
  The Vulkan engine compiles them (`vk/build.rs`); CB1's tests run in its
  `cargo test` (`vk/yblod/tests`).

References:

- [ETSI GS CCM 001 V1.1.1](https://www.etsi.org/deliver/etsi_gs/CCM/001_099/001/01.01.01_60/gs_ccm001v010101p.pdf)
- [FFmpeg Dolby metadata interface](https://ffmpeg.org/doxygen/trunk/dovi__meta_8h.html)
- [dovi_tool extension metadata](https://github.com/quietvoid/dovi_tool/tree/main/dolby_vision/src/rpu/extension_metadata/blocks)

These are implementation references, not a claim of independent clean-room
development or licensed-decoder conformance. Existing source comments and
limitations are retained. Historical optional experimental paths present in
the implementation are not all qualified; only explicitly recorded build and
runtime selections should be used for a release.

No movie fixtures, device captures, credentials or external binary-module
importer are part of this directory. The Kodi/FFmpeg integration and packaged
driver dependencies have their own source and license requirements.
