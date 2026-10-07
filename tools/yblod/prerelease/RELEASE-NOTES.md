# yblod 0.2-pre1 — experimental Profile 7 dual-QSV playback

Unofficial LibreELEC 13 Generic x86_64 testing build. This is a prerelease,
not a stable upgrade or an official Kodi/LibreELEC/Dolby/Intel product.
Back up your Kodi configuration first. Use a spare USB installation if possible.

## What changed

- Experimental native C/GPU reconstruction for Profile 7 FEL.
- QSV decoding of both base and enhancement layers, preserving each picture's
  Dolby instructions, timestamps and colour properties through the handoff.
- Intel media-engine enhancement-layer scaling and the measured planar-output
  optimizations. Scaling remains bilinear; nearest-neighbour was not validated.
- Fixed decoder selection and renderer validation so streams without an
  enhancement layer are not incorrectly rejected by the dual-QSV checks.
- Matching FFmpeg 9.0.2, Intel VPL dispatcher 2.17.0 and VPL GPU runtime 26.3.5
  are included. Intel iHD Media Driver 26.3.5 is retained from the tested base OS.
- TV-led output: the TV still applies the final Dolby Vision display mapping.
  No new Enhanced look or AI-generated metadata is enabled.

## Evidence and limitations

The exact Kodi/runtime combination was checked on an i5-1135G7 VM with an LG TV.
A short Saving Private Ryan P7 check exercised both QSV decoders with advancing
output and no reported drops/stalls. A roughly 35-second 12 Angry Men P8 check
had zero drops, stalls or renderer/presentation failures and one startup skip.
These are smoke checks, not whole-film certification or visual proof of every
displayed frame. Earlier matched P7 tests are documented on the experimental
branch. N100 performance and compatibility are NOT yet validated.

This package combines the matching direct-test4 base OS with the tested new
Kodi/decoder libraries. It is not a fresh rebuild of every operating-system
package. Source snapshots and a runtime/checksum manifest are included.
The packaged image must also pass a boot/playback smoke check before publication.

## Install

- New/spare installation: write the `.img.gz` with the LibreELEC USB-SD Creator
  or another image writer. This overwrites the chosen USB/storage device.
- Existing compatible Generic x86_64 LibreELEC 13 installation: copy the `.tar`
  into the `Update` share (`/storage/.update`) and reboot. Do not use on CoreELEC,
  ARM devices, Docker-only Kodi or another LibreELEC architecture.
- Verify downloads using `SHA256SUMS`. This prerelease is not added to the stable
  automatic-update channel. The previous 0.1 release remains available.
- Use a direct HDMI connection to a Dolby Vision-capable TV for the first test.
  Enable native Dolby Vision support in Kodi's Dolby Vision settings if needed.
- Remove your own old experimental Kodi/library overrides before testing;
  they can replace the packaged executable or libraries and invalidate results.

## N100 testing requested

Try a few minutes of known Profile 7 FEL content, including seek, pause/resume
and stop back to the menu. Also try P8 and ordinary HDR10/SDR as regression checks.
Report the N100 model, RAM, TV, HDMI connection/receiver, output resolution/rate,
title/profile, dropped/skipped frames, visible freezes/artifacts and a Kodi log.
GPU render/decode/video-processing utilization is welcome if available.
Do not upload copyrighted films, decoded frames or raw Dolby metadata.
Report issues at https://github.com/dangerouslaser/libreelec-yblod/issues.

## Sources

The release tag points to the public `experiment/dv-reconstruction` branch.
`yblod-0.2-pre1-playback-sources.tar.gz` includes the exact modified Kodi/native
engine and FFmpeg sources plus Intel VPL source trees used by this runtime.
The repository contains the base OS recipes, patches, native engine and build
controllers. Copyright and licence notices are retained in the source and
LibreELEC update bundle. Local Docker image IDs used in historical test tooling
are cache identifiers, not public registry downloads.
