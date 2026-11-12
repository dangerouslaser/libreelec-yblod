# Kodi patches

YBLOD's Kodi changes are one series of patches on Kodi `e6192109`. The files
live in two owner folders, `yblod/patches/kodi/` (general fixes) and
`yblod-engine/patches/kodi/` (Dolby Vision), and are linked into
`projects/Generic/patches/kodi/` (`yblod/tools/link-patches.sh --fix`), where
LibreELEC applies them after `packages/mediacenter/kodi/patches/*.patch`, in
file-name order (`LC_ALL=C`). Each file is `git format-patch` output whose
message says what the patch is for, what it needs and which earlier patches it
replaces.

## Names

`kodi-99NN-<area>-<subject>.patch`, in three ranges so that either folder can
take a new patch without renumbering the other:

| Numbers | Folder | What |
| --- | --- | --- |
| 9900-9949 | `yblod/patches/kodi/` | General fixes. Each applies to Kodi as LibreELEC patches it, on its own. |
| 9950-9989 | `yblod-engine/patches/kodi/` | Dolby Vision, in dependency order. The patches build only together; `HAVE_DVBRIDGE` is defined by 9957. |
| 9990-9999 | `yblod/patches/kodi/` | General patches that change code the Dolby Vision patches add, so they sort after them. |

A new patch takes the next free number in its range.

## The series

| File | What it does | Lines added / removed |
| --- | --- | --- |
| `yblod/patches/kodi/kodi-9900-guilib-image-animation-restarts-when-shown.patch` | guilib: an image's animated texture restarts each time it shows | +18 / -0 |
| `yblod/patches/kodi/kodi-9901-guilib-grouplist-wheel-from-scroll-destination.patch` | guilib: grouplist mouse wheel steps from the scroll destination | +8 / -3 |
| `yblod/patches/kodi/kodi-9902-input-mouse-pointer-stays-on-keys.patch` | input: a key can leave the mouse pointer up | +23 / -3 |
| `yblod/patches/kodi/kodi-9903-activeae-sink-retry-and-display-lost.patch` | ActiveAE: reopen the sink after a failed init, answer DISPLAYLOST always | +37 / -3 |
| `yblod/patches/kodi/kodi-9904-videoplayer-realtime-passthrough.patch` | VideoPlayer: pass audio through for realtime (live) streams | +22 / -13 |
| `yblod/patches/kodi/kodi-9905-addons-preinstalled-addon-updates.patch` | addons: update the add-ons YBLOD pre-installs from its own repository | +14 / -0 |
| `yblod/patches/kodi/kodi-9906-vaapi-depth-and-chroma-from-sw-pix-fmt.patch` | VAAPI: take the surface bit depth and chroma from sw_pix_fmt | +14 / -12 |
| `yblod/patches/kodi/kodi-9907-ffmpeg-keep-draining-hardware-decoder.patch` | FFmpeg: keep draining a hardware decoder until it reaches EOF | +4 / -0 |
| `yblod/patches/kodi/kodi-9908-live-tv-start.patch` | VideoPlayer: start live TV sooner | +44 / -11 |
| `yblod/patches/kodi/kodi-9909-videoplayer-hable-default-tone-mapping.patch` | VideoPlayer: Hable is the default tone mapping method (it was off) | +1 / -1 |
| `yblod-engine/patches/kodi/kodi-9950-dv-stream-and-picture-metadata.patch` | Dolby Vision: carry stream and picture metadata through VideoPlayer | +101 / -1 |
| `yblod-engine/patches/kodi/kodi-9951-dv-dvbridge-library.patch` | Dolby Vision: add the tools/dvbridge library | +1571 / -1 |
| `yblod-engine/patches/kodi/kodi-9952-dv-decoder.patch` | Dolby Vision: decode both layers and the metadata in the FFmpeg decoder | +618 / -2 |
| `yblod-engine/patches/kodi/kodi-9953-dv-display-drm-and-diagnostics.patch` | Dolby Vision: display capabilities, DRM output state and diagnostics | +1590 / -26 |
| `yblod-engine/patches/kodi/kodi-9954-dv-gui-composite-hooks.patch` | Dolby Vision: GUI composite hooks | +66 / -9 |
| `yblod-engine/patches/kodi/kodi-9955-dv-settings-strings-and-player-info.patch` | Dolby Vision: settings, strings and player information | +1798 / -1 |
| `yblod-engine/patches/kodi/kodi-9956-dv-vulkan-engine-adapter.patch` | Dolby Vision: the Vulkan engine adapter | +2112 / -0 |
| `yblod-engine/patches/kodi/kodi-9957-dv-renderer-window-and-build.patch` | Dolby Vision: renderer, window and build switch | +2247 / -22 |
| `yblod-engine/patches/kodi/kodi-9958-dv-bridge-at-the-mode-size.patch` | Dolby Vision: the bridge (scanout, GUI raster, engine canvas) at the display mode's size | +84 / -34 |
| `yblod-engine/patches/kodi/kodi-9959-dv-sdr-output-and-fallback.patch` | Dolby Vision: "Convert to SDR" (the engine's SDR output as an ordinary RGB picture), its settings, automatic fallback | +440 / -66 |
| `yblod-engine/patches/kodi/kodi-9960-dv-hdr-videos-through-the-sdr-output.patch` | Dolby Vision: HDR10, HDR10+ and HLG videos through the SDR output, with the switch back to Kodi's tone mapping | +288 / -46 |
| `yblod/patches/kodi/kodi-9990-variable-refresh-rate.patch` | windowing: variable refresh rate (FreeSync) for refresh rate changes | +251 / -2 |

The patches up to `kodi-9957` and `kodi-9990` add the 10538 lines and remove
the 109 lines that separated LibreELEC's Kodi from YBLOD 0.5.0's; no line is
added by one of them and removed by another.

`kodi-9909` and `kodi-9958` to `kodi-9960` are the SDR output (after 0.5.0;
[OUTPUT-MODES.md](../../yblod-engine/docs/intel-dv/OUTPUT-MODES.md#convert-to-sdr)).
They are a layer on the series as it was, written without touching the
earlier files, so the three Dolby Vision ones do change lines that 9950 to
9957 added (132 of them); with them the whole series is +11205 / -110 against
LibreELEC's Kodi. `kodi-9990` still applies after them with no offset: what
they change in the files it patches is above its hunks and line for line.
When the series is next regrouped they fold into 9953 (DRM state), 9955
(settings and strings, 45126 to 45141), 9956 (the adapter) and 9957 (the
window and renderer).

## Where the old patches went

Until 0.5.0 the series was its own development history: 70 files
(`kodi-9990` to `kodi-9999-yblod-61`), with about a quarter of what the older
ones added removed again by later ones. They were regrouped into the series
above with the tree unchanged: replayed on Kodi `e6192109` and LibreELEC's
patches, the old and the new series give the same git tree
(`f495ff9e4d5376b202fcc6e7dad7764e9be0f80a`). Each old patch went into the
new ones its surviving lines are in; a line a later patch rewrote stayed with
the patch that first added it, except that Dolby Vision code never moved into
a general patch and VRR code never into a Dolby Vision one.

| Old patch | Now in |
| --- | --- |
| `kodi-9990-native-dv` | 9950, 9951, 9952, 9953, 9955, 9957 |
| `kodi-9993-fel-presentation-pairing` | 9951, 9952 |
| `kodi-9993-guiimage-restart-animation-when-shown` | 9900 |
| `kodi-9994-hdmi-recovery` | 9953, 9957 |
| `kodi-9994-input-mouse-pointer-stays-on-keys` | 9902 |
| `kodi-9995-diagnostics` | 9953, 9957 |
| `kodi-9995-realtime-passthrough` | 9904 |
| `kodi-9996-output-modes-and-info` | 9953, 9955, 9957 |
| `kodi-9997-dv-static-metadata-latch` | 9952 |
| `kodi-9997-grouplist-wheel-destination` | 9901 |
| `kodi-9998-activeae-sink-retry` | 9903 |
| `kodi-9999-activeae-display-lost` | 9903 |
| `kodi-9999-dv-display-reset` | 9957 |
| `kodi-9999-dv-single-modeset` | 9953, 9957 |
| `kodi-9999-vaapi-live-10bit` | 9906 |
| `kodi-9999-yblod-01-qsv-offload` | 9951, 9955, 9957 |
| `kodi-9999-yblod-02-dv-menu` | 9951, 9955, 9957 |
| `kodi-9999-yblod-03-native-source` | 9907, 9951, 9952, 9953, 9954, 9956, 9957 |
| `kodi-9999-yblod-04-native-startup` | 9957 |
| `kodi-9999-yblod-05-remove-legacy-settings` | nothing (all it added was removed later) |
| `kodi-9999-yblod-06-menu-target` | 9957 |
| `kodi-9999-yblod-07-sdr-restore` | 9953, 9957 |
| `kodi-9999-yblod-08-live-decoder-framerate` | 9908 |
| `kodi-9999-yblod-09-live-single-open` | 9908 |
| `kodi-9999-yblod-10-live-display-coordination` | 9957 |
| `kodi-9999-yblod-11-live-audio-preroll` | 9908 |
| `kodi-9999-yblod-12-native-gui-redraw` | 9954 |
| `kodi-9999-yblod-13-native-home-cache` | 9954 |
| `kodi-9999-yblod-14-native-async-pack` | nothing (all it added was removed later) |
| `kodi-9999-yblod-15-native-gui-revision` | 9956, 9957 |
| `kodi-9999-yblod-18-dolby-vision-category` | 9955 |
| `kodi-9999-yblod-20-optional-addon-updates` | 9905 |
| `kodi-9999-yblod-21-dv-engine-settings` | 9955, 9957 |
| `kodi-9999-yblod-22-native-pgs-subtitles` | 9954, 9957 |
| `kodi-9999-yblod-23-vulkan-engine` | 9955, 9956, 9957 |
| `kodi-9999-yblod-24-mel-no-el` | 9950, 9952, 9957 |
| `kodi-9999-yblod-25-vulkan-cb1-reference` | 9956, 9957 |
| `kodi-9999-yblod-26-amdgpu-opaque-framebuffer` | 9953 |
| `kodi-9999-yblod-27-vulkan-engine-sync` | 9956 |
| `kodi-9999-yblod-28-dv-stable-commit` | 9953 |
| `kodi-9999-yblod-29-vulkan-engine-split` | 9951, 9956, 9957 |
| `kodi-9999-yblod-30-vulkan-only` | 9951, 9955, 9956, 9957 |
| `kodi-9999-yblod-31-dv-tunnel-hdr10` | 9953, 9955, 9956, 9957 |
| `kodi-9999-yblod-32-dolby-vision-menu` | 9953, 9955, 9956 |
| `kodi-9999-yblod-33-el-bilinear` | 9956 |
| `kodi-9999-yblod-34-hdr10plus` | 9952, 9953, 9955, 9956, 9957 |
| `kodi-9999-yblod-35-even-geometry` | 9957 |
| `kodi-9999-yblod-36-variable-refresh-rate` | 9990 |
| `kodi-9999-yblod-40-dv-surface-without-texture` | 9957 |
| `kodi-9999-yblod-41-dv-software-pictures` | 9957 |
| `kodi-9999-yblod-42-dv-surface-pool-reset` | 9956 |
| `kodi-9999-yblod-43-dv-hold-repeated-picture` | 9953, 9956, 9957 |
| `kodi-9999-yblod-44-dv-gui-unchanged` | 9956, 9957 |
| `kodi-9999-yblod-45-dv-engine-recovery` | 9956, 9957 |
| `kodi-9999-yblod-46-dv-restore-retry` | 9957 |
| `kodi-9999-yblod-47-dv-scaler-latch` | 9956, 9957 |
| `kodi-9999-yblod-48-dv-housekeeping` | 9956, 9957 |
| `kodi-9999-yblod-49-dv-queued-flips` | 9953, 9956, 9957 |
| `kodi-9999-yblod-50-fel-resync` | 9951, 9952 |
| `kodi-9999-yblod-51-dv-decoder-fallback` | 9952 |
| `kodi-9999-yblod-52-dv-edid-eeodb` | 9953 |
| `kodi-9999-yblod-53-addon-repository-pinning` | 9905 |
| `kodi-9999-yblod-54-string-ids` | 9955, 9990 |
| `kodi-9999-yblod-55-dvbridge-unused` | 9951 |
| `kodi-9999-yblod-56-unused-leftovers` | 9951, 9956 |
| `kodi-9999-yblod-57-diagnostics-cost` | 9953, 9955 |
| `kodi-9999-yblod-58-decode-allocations` | 9950, 9952, 9957 |
| `kodi-9999-yblod-59-string-ids-in-render` | 9955, 9956, 9957 |
| `kodi-9999-yblod-60-spdx-tags` | 9956 |
| `kodi-9999-yblod-61-hdr10plus-flags-type` | 9957 |
