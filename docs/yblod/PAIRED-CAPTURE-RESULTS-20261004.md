# Direct conversion: same-frame checks, 2026-10-04

The shorter conversion path closely preserved all eight sampled frames from
**1917** and **Saving Private Ryan**. Across the measured picture area, **99.1371%
of the stored picture values were identical**. Every remaining difference was
exactly one step on the 4,096-step scale. Both versions carried identical,
CRC-valid Dolby Vision metadata in every pair.

This supports keeping the change as a promising performance optimization. It
does **not** demonstrate improved colour accuracy, prove equivalence for every
frame, or replace comparison with a licensed hardware player.

## Build and setup

- Built on Ollie using the existing memory-limited build script.
- Image: `LibreELEC-Generic.x86_64-13.0-yblod-0.1-direct-test3.tar`.
- Source/build ID on Ollie: `b9036001330cd15047bf6c02bfcc6198d388e88f`.
- Archive SHA-256:
  `5da1288d6f498db232445b3735f51d2e48206384b72cb862bda781ed82f23f47`.
- Installed and rebooted the LibreELEC VM on Petunia, `192.168.1.175`.
- The original release's rollback files and the previous test archive remain
  under `/storage/backup`.
- Quick Sync enhancement-layer scaling enabled (mode 1); hardware-matching
  colour offset enabled; subtitles disabled during captures.
- Each pair used the very same decoded base/enhancement surfaces and input
  metadata, rendered into an offscreen target through each conversion path.
  Base and enhancement timestamps matched in all eight captures.
- Only the conversion path changed between each pair. This is not an A/B test
  of the enhancement scaler, chroma filter, or hardware-matching offset.

## Results

The comparison excludes black bars and metadata-bearing rows. It measures
native 12-bit I, P, and T codes without alignment, fitted bias removal, RGB
conversion, or perceptual weighting. I has twice as many stored samples as each
chroma channel; percentages below count those stored samples, not RGB pixels.

| Film | Source timestamp (s) | Capture directory | Identical values | Largest difference |
|---|---:|---|---:|---:|
| 1917 | 609.776 | `pair-kle6AW` | 99.2584% | 1 code |
| 1917 | 3969.966 | `pair-9DqgC6` | 99.7254% | 1 code |
| 1917 | 4209.956 | `pair-cs0WNT` | 99.8084% | 1 code |
| 1917 | 4810.014 | `pair-xLdPr2` | 99.7131% | 1 code |
| Saving Private Ryan | 490.031 | `pair-zAchmP` | 98.9894% | 1 code |
| Saving Private Ryan | 3909.989 | `pair-JsYZkP` | 99.1289% | 1 code |
| Saving Private Ryan | 8109.893 | `pair-hdBrbw` | 98.6098% | 1 code |
| Saving Private Ryan | 9310.051 | `pair-C5x0hW` | 98.3634% | 1 code |

Total: 115,668,480 stored samples; 114,670,377 identical; 998,103 differing by
one code. No measured sample differed by two or more codes. These are numeric
signal comparisons, not a claim that a one-code difference is always invisible.

Renderer summaries after both films reported zero presentation failures and
zero stage failures. Captures deliberately stall for GPU readback and disk
writes; this run is **not** a performance benchmark or a dropped-frame test.
The earlier performance measurements remain in
`DIRECT-CONVERSION-RESULTS-20261004.md`.

## TV standby and reference device

After the user switched off the TV, the VM's HDMI-A-2 connector stayed connected
and enabled, with its 256-byte EDID still readable. Playback continued without
new reported drops/skips in the observed intervals. The update reboot and Kodi
restarts also succeeded with the TV off. This establishes that this particular
standby setup supports continued software testing; it is not a measurement of
what the powered-off panel displays or a guarantee about later deep standby.

SSH access to the SK4 Pro at `192.168.1.180` was verified after the user added the
existing reference-device public key. It runs CoreELEC
`22.0-Piers_nightly_20261002`, has the VDIN1 capture interface, reports a connected
Dolby Vision-capable display, and has both films in its library. Its playback and
settings were not changed. **No SK4 reference frames were captured or scored in
this run.**

## Artefacts and cleanup

- VM: `/storage/dvbridge-captures/pair-*`, `capture-kodi.log`, and
  `capture-os-release`.
- Ollie repository: `target/direct-test3-captures/pair-*` and `comparison.json`.
- Capture instructions: `PAIRED-CAPTURE-TEST.md`.
- The temporary systemd capture override was moved to
  `/storage/dvbridge-captures/90-dvbridge-capture.conf.disabled`, systemd was
  reloaded, and Kodi was restarted. Its service environment no longer enables
  capture. Subtitles were turned back on for both test films.
- After cleanup, Saving Private Ryan ran normally with the TV off. Five
  consecutive 10-second health intervals reported no stalls, no new drops, and
  no new skips; renderer failure counters remained zero. One skip had been
  reported at playback startup, before these intervals. Test playback was then
  stopped, leaving Kodi running.
- Experimental direct conversion remains enabled on the test VM; the image's
  setting default remains off. No changes were pushed to GitHub.

The next accuracy step is to obtain **unambiguously matching source frames**
from the SK4 and compare both alternatives against them. Similar playback-clock
times alone are not sufficient to claim matching frames or improved accuracy.
