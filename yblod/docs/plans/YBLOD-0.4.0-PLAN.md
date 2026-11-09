# YBLOD 0.4.0 plan: Vulkan only, HDR10/HDR10+ conversions, CM4.0, new Dolby Vision menu

Written 2026-11-09. Scope agreed with the owner:

1. Remove the CB1-derived compatibility renderer and the OpenCL engine.
2. The Vulkan engine is the only Dolby Vision renderer.
3. Dolby Vision -> HDR10.
4. Dolby Vision -> HDR10+.
5. HDR10+ -> Dolby Vision.
6. CM4.0.
7. EL upscaling: Bilinear or Annex B.
8. A Dolby Vision menu that shows only settings YBLOD actually applies.
9. Built on `main` with LibreELEC master merged in (the 2026-11-09 sync).

0.3.5 was never published to the update channels, so the NUC7 HPD fix
(linux-9931 v2, PR #27) ships in 0.4.0 instead of a separate 0.3.6. The six
decisions in section 1 are taken as written (owner goal, 2026-11-09).
Work branch: `feature/yblod-0.4.0`, started from the sync branch
`upstream/libreelec-20261109` (master merged, Kodi patches rebased).

## 0. Starting point (facts, 2026-11-09)

| Item | State |
|---|---|
| LibreELEC master -> main | Branch `upstream/libreelec-20261109` pushed: merge done, Kodi patches rebased on Kodi `e6192109`. Its Kodi/image build on Ollie was still running; PR and merge follow if it passes. **0.4.0 work starts from `main` after that merge.** |
| Vulkan engine (`yblod-engine/vk`) | big-fella `dv-engine-vk` 0.1.0-20 plus YBLOD's Kodi additions (`DVVK_OVERLAY_FLIP_Y`, `DVVK_SURFACE_CHECK`). In sync with big-fella's merged 0.1.0-20; the HDR10 output code is identical. |
| DV -> HDR10, engine | In `main` since 0.3.4: `dvvk_set_output_mode` / `dvvk_output_signal`, the Master Reference conversion (CB1 Reference Basic's mapping). Author check: within one 12-bit code of the CPU double-precision map. |
| DV -> HDR10, Kodi | `kodi-9999-yblod-29-dv-tunnel-hdr10.patch` (526 lines) on `feature/dv-hdr10-output` only. Compile-checked, never played. Sends the engine's HDR10 through the tunnel as 12-bit YCbCr 4:2:2 with `DVBRIDGE_TUNNEL_FORMAT=hdr10` (linux-9928, native HDMI connectors only). |
| DV -> HDR10 today | "Convert Dolby Vision to HDR10" runs on the compatibility renderer (libplacebo spline tone mapping, OUTPUT-MODES.md). Removing that renderer removes this path. |
| CM4.0 | In the engine already: `yblod/dm_cm4.c`, adapted from CB1 `cb1_cmv40.c` (CB1 0.5, 2026-11-01; unchanged in CB1 since). `DV_VULKAN_CM4=off` by default (modes off, no-l2, always, auto, auto2; tunables `DV_VULKAN_CM4_TRIGGER`, `_HEADROOM`, `DV_VULKAN_TV_PEAK`, `DV_VULKAN_NO_L2`). Golden hashes include CM4 cases. Not in the menu. |
| EL upscaling | Both engines: nearest (2x2 repeat) or CCM Annex B. With `DV_VULKAN_CB1=1` (default) unscaled pictures are always Annex B. No bilinear EL path exists. |
| HDR10+ | Nowhere in YBLOD or big-fella. CroqueMr's CB1 has native HDR10+ output, DV -> HDR10+ and HDR10+ -> DV (`CB1/docs/HDR10PLUS.md`): host C `cb1_hdr10plus*.c`, `cb1_dv_hdr10plus.c` (about 800 lines, GPL-2.0-or-later), GPU statistics on libplacebo, kernel `linux-9940-hdr10plus` (394 lines), `-9941-presentation-contract` (56), `-9942-intel-internal-recovery` (36), on Linux 7.2.6. CB1's own docs: HDR10+ -> DV tested on N100/Ryzen; native HDR10+ output and DV -> HDR10+ not yet. |
| Validation oracles | `golden.sh` (90 hashes); `~/cb1-hdr10-ref` on Ollie: CB1's DV -> HDR10 circuits rendered headless (1917 FEL, 28 Years Later P8.1, Gemini Man MEL, a 4000-nit demo). |

## 1. Decisions to confirm before work starts

1. **"Remove CB1" keeps CB1's Master Reference *processing* inside the Vulkan engine** (`cb1_contract`: siting, 4:2:0 reshaping, Annex B EL and 4:2:2 filters, metadata order). It's the reference that "Annex B (Master Reference)" names, and it's byte-identical to CB1's. Only CB1's renderer (DVBridgeGLES/libplacebo) and its menu leftovers go.
2. **EL upscaling semantics:** "Annex B (Master Reference)" = today's default (`cb1_contract` for unscaled pictures, Annex B everywhere). "Bilinear" = YBLOD's own processing with a new bilinear EL pass, for every picture. Nearest is removed (CB1 removed it in RC3 as visibly worse).
3. **HDR10 / HDR10+ outputs are native HDMI (gen12+ Intel, amdgpu) only in 0.4.0.** The converter routes (INUC 11 linux-9930, NUC7 linux-9931) carry only the DV tunnel format: no HDR10 tunnel format, no DRM InfoFrame DIP on the NUC7's gen9 in level-shifter mode. On those boxes the HDR10/HDR10+ output modes are hidden. They get Dolby Vision or nothing, until a later lab round proves a route.
4. **If the Vulkan engine cannot start**, Dolby Vision titles fall back to Kodi's plain base-layer playback (correct for P8.1, FEL lost for P7, wrong colours for P5) with a one-time notification. No second renderer.
5. **Native HDR10+ passthrough** (HDR10+ source -> HDR10+ output) comes almost free once the HDR10+ output path exists (workstream E). In scope as a by-product, not a goal.
6. **CM4.0 default:** off, as today, exposed in the menu (A/B against the TV first). Changing the default is a later decision with test evidence.

## 2. Workstreams

Branch per workstream from `main` (after the sync merge), PRs into `feature/yblod-0.4.0`, which is released from. A-C can run in parallel; D needs C's output-mode plumbing; E needs the kernel part of D; F needs B's frame plumbing.

### A. Vulkan only: remove the OpenCL engine and the compatibility renderer

- **Kodi patches.** Inventory, then cut:
  - The OpenCL `CDVPrivateSource` path: `DV_PRIVATE_SOURCE` without `DV_ENGINE_VULKAN`, and `libdv_source_private` loading.
  - DVBridgeGLES's libplacebo rendering and the QSV offload's libplacebo upscalers (`yblod-01`, `-16` chroma upscaler, `-17` compat renderer menus).
  - The engine/Vulkan toggles (`yblod-21`, `-23`, `-27`).
  - Keep the DV tunnel scanout, metadata, GUI overlay, startup/sync and live-TV patches (`yblod-03..15`, `-22`, `-24`, `-28`, `9990-9997`). Several touch DVBridgeGLES; split carefully, rebuild the series, zero fuzz.
- **Engine sources.** Keep `yblod-engine/src`'s host C that `vk/build.rs` compiles in (tables, metadata serializer, `dv_ffmpeg_metadata.c`, plan inputs). Remove the OpenCL backend, kernels, `libdv_source_private.so` packaging, and the OpenCL-only tools/tests. `yblod-engine/CMakeLists.txt` keeps a host-C-only target, or `build.rs` takes the file list directly.
- **Packages.** Drop the OpenCL engine package and its runtime deps (OpenCL ICD) from the image if nothing else needs them. Keep `yblod-engine-vk`.
- **runtime.env.** Remove `DV_PRIVATE_SOURCE_LIBRARY`, the OpenCL-only `DV_OVERLAY_*` / `DV_*TABLE_CACHE*` / `DV_RECON_ACTIVE_ROWS` / inline-overlay variables, `DV_ENGINE_VULKAN` (always on). Keep what the Vulkan adapter reads, audited from the code, not from the file.
- **Failure path.** Decision 4: notification and log line; no silent fallback.
- **Done when:** a clean build with no OpenCL/libplacebo DV code in Kodi; P5/P7 FEL/P7 MEL/P8.1 play through Vulkan; `golden.sh` identical; DV start/stop, seek, GUI over video, live TV unchanged on the N150 and the IT11.

### B. EL upscaling: Bilinear or Annex B (Master Reference)

- **Engine.** Replace the `nearest` push constant in the FEL shaders (`fel_chroma.comp`, `fel_vertical_pair*.comp`, `fel_scale_horizontal.comp`, `fel_phase_vertical_uv.comp`, `fel_luma_phase_guide.comp`, `fel_mmr_dual_horizontal.comp`) with a method: 0 Annex B, 1 bilinear.
  - Bilinear: the EL at half resolution upsampled with 2-tap linear interpolation at the stream's EL sample phase. Same phase convention as Annex B, so only the filter changes.
  - Host side: `dvvk_frame.plan.el_scaler` becomes the method; ABI version bump if the struct meaning changes.
- **Reference.** CPU reference for bilinear in the host C (replacing `dv_nearest_scale2x`), used by `Verify output` and `cargo test`.
- **Golden hashes.** Annex B hashes unchanged. New bilinear hashes recorded on the N150 and Ollie (UHD 770) and checked identical across them. Remove the nearest hashes.
- **Kodi adapter.** "Annex B (Master Reference)" -> `cb1_contract` for unscaled pictures plus Annex B. "Bilinear" -> `cb1_contract` off, bilinear EL. Setting `dvbridge.elupscaler` replaces `dvbridge.elnearest`.
- **Done when:** both modes play P7 FEL / MEL correctly; golden hashes as above; GPU time of bilinear <= Annex B on the N150 (otherwise say so in the menu help).

### C. Dolby Vision -> HDR10 on Vulkan

- Rebase `kodi-9999-yblod-29-dv-tunnel-hdr10` onto the synced Kodi and onto workstream A (it currently coexists with the GL conversion; that fallback goes).
- Output mode "Convert Dolby Vision to HDR10" uses the engine's HDR10 output through the tunnel (12-bit YCbCr 4:2:2, `DVBRIDGE_TUNNEL_FORMAT=hdr10`) with `HDR_OUTPUT_METADATA` from `dvvk_output_signal`. Hidden where the connector lacks the tunnel format (converter routes, decision 3).
- **Validation:**
  - The engine's HDR10 output against `~/cb1-hdr10-ref` (CB1 Reference Basic) on the four titles. Report the max code difference; expectation from the author: at most one 12-bit code.
  - Then on a TV (IT11 + LG G5): HDR badge, correct picture, DV<->HDR10 mode changes, seek, GUI over video.

### D. HDR10+ output path (kernel + Kodi), needed by E and native HDR10+

- **Kernel.** Port CB1's `linux-9940-hdr10plus` (HDR10+ vendor InfoFrame, OUI 0x90848B, ST 2094-40 HDMI packing, per-frame updates), `-9941-presentation-contract` (the packet belongs to the same atomic commit as its framebuffer) and `-9942-intel-internal-recovery` from Linux 7.2.6 to our 7.3 (i915 VS DIP on gen12+; amdgpu). Our linux-9900/9928 already own the VS DIP for the Dolby VSIF: the two must be mutually exclusive per commit, enforced in `intel_hdmi_compute_config` and the amdgpu equivalent. New `yblod` patch number after 9931.
- **Kodi.** An HDR10+ metadata property per frame on the atomic commit (CB1's contract), set from FFmpeg `AV_FRAME_DATA_DYNAMIC_HDR_PLUS` for native sources (decision 5) or from the engine (E). Cleared on seek, source change, rejected import and teardown.
- **Validation:** an HDR10+ TV (Samsung, or a Panasonic/Philips with HDR10+) in the lab. LG sets do not support HDR10+. Volunteer hardware needed; see section 4.

### E. Dolby Vision -> HDR10+

- **Engine.** Output mode "HDR10+": the Master Reference reconstruction in BT.2020 PQ **without** tone mapping (CB1: the receiver applies the curve once), plus per-frame statistics of the active film area before GUI composition: per-channel linear maxima, average maxRGB, a 256-bin histogram. A new Vulkan compute pass (CB1 does this on libplacebo), reduced on the GPU, read back one frame late.
- **Host C.** Port `cb1_dv_hdr10plus.c`, `cb1_hdr10plus_curve.c`, `cb1_hdr10plus_analysis.c`, `cb1_hdr10plus.c`:
  - L1/L3/L2/L8 resolution.
  - One luminous curve fit, 992-nit reference.
  - Quantized-curve validation (max normalized PQ error 2/1023).
  - V0/V1 packing; HDR10 fallback when the curve can't be represented.
  Into `yblod-engine/src` (host C compiled into the Vulkan engine), keeping CB1's GPL-2.0-or-later notices.
- **Kodi.** Output mode "Convert Dolby Vision to HDR10+" -> engine HDR10+ mode + D's per-frame packet. Falls back to HDR10 (C) when the TV has no HDR10+ in its EDID.
- **Validation:** CB1's software tests ported (byte layout, curve quantization, invalid inputs, L1/L3/L2/L8 coverage, frame ownership); statistics against a CPU reference on the golden titles; on an HDR10+ TV, the HDR10+ badge and a picture matching the HDR10 conversion's intent.

### F. HDR10+ -> Dolby Vision

- **Approach.** Treat an HDR10+ stream as a Profile 8.1 base layer with a synthesized RPU, so the existing tunnel path renders it unchanged:
  - Port `cb1_hdr10plus_dovi.c`: validated single-window MaxSCL as the source peak; mean PQ from weighted percentile trapezoids (AVDVPlus HistogramPlus); estimated L3 folded once; neutral output L3; no invented trims.
  - Generate L1 (+ L6 from static metadata) per picture.
  - Feed the engine as P8.1 with an identity composer.
- **Kodi.** Source detection (HDR10+ side data, single window), an "HDR10+ sources: Native / Dolby Vision" setting (shown only with a DV-capable sink); the decoded frame's HDR10+ metadata travels with the picture to the engine (same frame ownership as the RPU path).
- **Validation:** CB1's tests ported; the RPU generator against `dovi_tool` parsing (valid, the expected L1 per scene); on the LG C3/G5: DV badge, picture brightness consistent with the HDR10 rendering of the same title, no flicker at scene cuts.

### G. CM4.0

- **Parity.** Confirm `dm_cm4.c` matches CB1 `cb1_cmv40.c` at CB1 0.5 (unchanged since 2026-11-01), including the auto/auto2 decisions; the existing CM4 golden cases stay identical.
- **Menu.** "Dolby Vision metadata: Original (CM2.9) / CM4.0 always / CM4.0 auto", plus "Remove L2 trims", plus, for auto2, the TV peak (nits, from EDID when present). Only applied by the Vulkan engine, which is now always the case.
- **Validation:** A/B on the LG C3 and G5 with the four reference titles; document the visible effect and keep the default off unless the evidence says otherwise (decision 6).

### H. The Dolby Vision menu

Settings > Player > Dolby Vision, rebuilt from what the code applies (every entry traced to the variable or call it sets; nothing that only affected OpenCL or libplacebo):

- **Video**
  - Output mode: Dolby Vision (TV-led) / Convert to HDR10 / Convert to HDR10+ / Off. The HDR10 options only where the connector supports them; HDR10+ only with an HDR10+ sink.
  - HDR10+ sources: Native HDR10+ / Dolby Vision (only with a DV sink).
  - Enhancement layer upscaling: Annex B (Master Reference) / Bilinear.
  - Dolby Vision metadata (CM4.0): Original / CM4.0 auto / CM4.0 always; Remove L2 trims; TV peak brightness (auto2).
  - Enhanced player information.
- **Menu output** (DV menu mode; unchanged, verify each against the Vulkan GUI path): Dolby Vision for the menu, brightness, saturation, gamma, wide colour.
- **Performance** (expert level), only where the Vulkan adapter reads them:
  - Process only the picture area: check that the Vulkan path honours `DV_RECON_ACTIVE_ROWS`; drop it if not.
  - Reuse unchanged controls / home screen (`DV_PRIVATE_GUI_CACHE*`, read by Kodi itself).
  - Prepare frames ahead (`DV_PRIVATE_ASYNC_PACK`, verify on Vulkan).
  - Half-resolution menus (`DV_PRIVATE_GUI_HALF`).
- **Diagnostics** (expert): Verify output (against the CPU reference: Annex B and bilinear), frame timing log, GPU timing log. Each re-pointed at what the Vulkan engine emits.
- **Removed:** Native Dolby Vision engine, Vulkan engine, Colour upscaling (Gaussian/Lanczos), Nearest-neighbour enhancement layer, Fast on-screen controls (`DV_OVERLAY_INLINE`, OpenCL only), Reuse reshaping tables (`DV_*TABLE_CACHE`, OpenCL only). Their setting IDs get a settings-migration entry so old `guisettings.xml` values are dropped cleanly.
- Strings rewritten; help text states when a setting applies ("next video") and on which outputs.

## 3. Order and milestones

| # | Milestone | Contents | Gate |
|---|---|---|---|
| M0 | Base | Sync PR merged into `main`; 0.3.6 released from it | 0.3.6 shipped |
| M1 | Vulkan only | A + H (menu without the new modes) + G's menu entries | Clean build, golden identical, N150/IT11 playback |
| M2 | EL scaling + HDR10 | B + C | Golden (Annex B identical, bilinear recorded), cb1-hdr10-ref comparison, IT11 + G5 TV test |
| M3 | HDR10+ output | D (+ native passthrough) | HDR10+ TV lab test |
| M4 | DV -> HDR10+ | E | Ported tests, statistics reference, HDR10+ TV |
| M5 | HDR10+ -> DV | F | Ported tests, dovi_tool check, LG TV test |
| M6 | 0.4.0-test1 | All of the above, both editions | Volunteer runs (N150, IT11, INUC 11, NUC7: DV paths unchanged on converter routes) |
| M7 | 0.4.0 | Release notes, validation report, channels | Owner sign-off |

M1 and M2 can be released as test builds on their own. M3-M5 depend on access to an HDR10+ TV.

## 4. Hardware needed

- LG G5 + IT11 (owner): DV, HDR10, CM4 A/B, menu.
- LG C3 + NUC7 (volunteer woodenalbatross): converter-route regression; HDR10+ -> DV on an LG.
- INUC 11 + Sony Bravia 7 (volunteer Silberbak): converter-route regression.
- N150: performance, golden hashes.
- **An HDR10+ TV** (Samsung, or a Panasonic/Philips with HDR10+): no one in the current set has one. Required for D and E. Find a volunteer, or use the NUC Display Lab with HDR10+ test frames.

## 5. Risks

- **Removing the fallback renderer:** any Vulkan start failure means no DV picture. Mitigation: the failure notification, and a test matrix covering Intel gen12+ and AMD.
- **Kodi patch surgery:** DVBridgeGLES is shared by the tunnel and the compatibility path. Split it in a first, behaviour-neutral PR before deleting anything.
- **VS DIP contention:** Dolby VSIF vs HDR10+ VSIF on one DIP. Enforce one per commit in the kernel; the state checker must agree.
- **HDR10+ curve fitting is approximate by design:** CB1's own docs. Say so in the menu help and release notes.
- **CB1 parity drift:** port from a pinned CB1 commit; record it in each ported file's header, as `dm_cm4.c` does.
- **Converter routes:** they keep DV only; the menu must hide what they can't do rather than fail at playback.
