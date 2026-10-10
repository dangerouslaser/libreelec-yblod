# YBLOD 0.2 release candidate

Changes since YBLOD 0.1, including the work shipped in 0.2-pre1 through pre7.
The final upstream-resynced image is undergoing release checks. No final 0.2
release has been published by this document.

## Native Dolby Vision playback engine

YBLOD now uses its standalone C/OpenCL source-picture reconstruction and packing
engine inside Kodi. Decoded video surfaces stay on the GPU, and planar
intermediates avoid unnecessary copies and colour conversions. Frame metadata
stays paired with the picture through decoding, reconstruction and presentation.
The output remains Standard TV-led Dolby Vision; the television performs display
mapping. CM4 metadata transport is not a player-side implementation of CM4 display
mapping.

The engine supports the tested Profile 7 FEL and single-layer playback routes,
with validation of source geometry, metadata and buffer ownership. Fixes include
preserving the FEL correction for polynomial chroma mapping, which resolves the
black picture in the DT/DL P7 CMV4.0 4000-nit v3 test clip. Selected profile and
lifecycle evidence is recorded in the [adapter qualification reports](../native-dv/integration/README.md).

The old Quick Sync scaling and Match Dolby hardware levels controls are removed;
saved values cannot reactivate those legacy behaviours. Intel hardware video
decoding remains enabled. The new engine and adapter are public source, separate
from the bulk of Kodi for easier inspection and development.

## Playback efficiency

- Reuse cached GUI colour calculations and unchanged Home-screen graphics.
- Tell the engine when Kodi has not redrawn the GUI, skipping the full-screen
  unchanged-pixel scan.
- Skip unnecessary cached-colour reads for fully transparent GUI pixels.
- Run movie-only tunnel packing ahead into a second display buffer while retaining
  frame identity and buffer-ownership checks.
- Keep asynchronous overlay packing disabled: its experimental implementation
  worsened frame delivery in the measured 4K60 controls-open test.

Selected N150 comparisons from the prerelease development cycle:

| Comparison | Before | After |
| --- | ---: | ---: |
| FEL with Home visible, GUI caching | 100.75 ms | 15.37 ms |
| P8.4 with Home visible, GUI caching | 93.02 ms | 15.56 ms |
| FEL movie-only asynchronous packing | 13.49 ms | 10.71 ms |
| P8.4 movie-only asynchronous packing | 11.29 ms | 8.86 ms |
| Gemini Man controls, GUI reuse plus transparent reads | 22.29 ms | 11.44 ms |

These are median CPU-side processing/wait counters from separate controlled
comparisons, not GPU utilisation, full decode-to-display latency, or a direct
0.1-versus-0.2 benchmark. They are not additive. The final row covers bounded early
samples in a roughly 30-second 4K59.94 run: drops changed from 55 to 32, and skips
from 0 to 1. It does **not** establish smooth 4K60 playback with controls open.
The earlier measurements were made before the final upstream resync.

See [GUI caching](GUI-CACHE-20261010.txt), [asynchronous packing](ASYNC-PACK-20261010.txt)
and [GUI revision reuse](GUI-REVISION-20261010.txt) for methods and limitations.
Pixel/reference tests establish implementation consistency, not independent
Dolby conformance or equality to every licensed player.

## Menus and playback controls

- Coordinate Dolby Vision startup before releasing the playback clock.
- Fix distorted or repeated menus after stopping native Dolby Vision playback.
- Clear stale HDR signalling when returning to SDR menus.
- Keep controls and subtitles visible over Level 5 letterbox bars. While an
  overlay is present, clear the outgoing active-area restriction, restoring it
  afterward without changing the movie pixels or original frame metadata.
- Keep Home visible while a movie plays in the background and redraw its target
  correctly.
- Preserve YBLOD's QMS refresh switching and Dolby Vision menu appearance controls.

## Faster live TV

- Avoid opening live MPEG-TS streams twice during startup.
- Use the decoder's actual frame-rate information early instead of imposing one
  fallback rate on mixed-frame-rate playlists.
- Coordinate refresh-rate and colour-mode changes before presentation.
- Reduce initial audio buffering to the buffered duration plus 100 ms headroom,
  retaining the existing synchronisation constraints.
- Retain the live 10-bit picture fix.

On the Intel VM, the duplicate-open fix reduced playback-start notifications from
about 3.8–4.5 seconds to 2.4–3.0 seconds in the initial channel comparison.
Separate display coordination tests reduced signal commits from two to one.
Channel 5 to ESPN software audio timing correction fell from 698 ms to 118/113 ms
in two candidate runs. Notifications and software timing are not measurements of
the first visible picture or audible soundbar output.

## Updated LibreELEC base

The source is resynced through LibreELEC master
`cd5ed44f054deff79f50fc748995d8e77942ce6b`. This includes the earlier Kodi/base
resync and the final SQLite 3.54.0, aom 3.15.2, pycparser 3.11 and Kodi startup-log
updates. YBLOD's Intel display patches, QMS and Dolby Vision menus remain in place.
This is a LibreELEC development base, not an official stable LibreELEC release.

## Known limitations

- Experimental, Intel-focused Dolby Vision support; no Dolby certification.
- N150 4K59.94 playback can still drop frames with controls open.
- AMD OpenCL integration, AMD Dolby Vision signalling and a general native-engine
  DV-to-HDR10 fallback are not added. Unsupported P5 playback may have incorrect
  colours rather than valid SDR/HDR10 output.
- Retired DV profiles remain unsupported; profile 20 is deferred.
- QMS needs a compatible HDMI chain and does not eliminate HDR/SDR mode-change
  blackouts. Audio format changes may require a TV, AVR or soundbar to reconnect.
- Audio startup tuning still needs broader adverse-network, passthrough and
  physical lip-sync testing.
- The 4K GUI cache uses about 158 MiB of additional GPU-accessible memory.
- Short scene tests do not qualify every file, skin, display, subtitle format or
  long playback session. First playback may include shader compilation.

## Updating

Back up your settings. Use the release's `.tar` in `/storage/.update/` for an
existing LibreELEC installation, or `.img.gz` for a fresh installation. Match
checksums and read the exact packaged-image validation record before installing.
Local device networking, Home Assistant credentials and diagnostic overrides are
not part of the image.

For troubleshooting the new GUI optimizations, merge these entries into
`/storage/.config/native-dv.env`, preserving unrelated settings, and restart Kodi:

```ini
DV_PRIVATE_GUI_REVISION=0
DV_OVERLAY_SPARSE=0
```

This disables the latest two optimizations without changing the native engine,
the existing GUI pixel cache, or movie-only asynchronous packing.
