# Complete BL/EL QSV metadata handoff candidate

Experimental source, not a qualified default playback route.

The previous chroma-only candidate passed the base-layer guard but failed the
enhancement-layer metadata guard. This candidate carries complete per-picture
properties rather than consulting the latest decoder/parser context.

## Contract

- BL: snapshot the selected PPS/SPS's chroma location, range, primaries, transfer,
  matrix and sample aspect ratio beside the existing Dolby instructions, RPU,
  timestamp, duration and key-frame association token.
- EL: snapshot independently parsed geometry, software format and the same VUI
  properties beside each queued picture; commit only on successful submission.
  Restore that snapshot when its matching QSV output token returns.
- Check actual mapped geometry, native 10-bit format, crop/progressive constraints,
  owned GPU device and frame lifetime. Preserve flush/generation boundaries.
- Missing colour descriptions remain UNSPECIFIED. The HEVC-defined chroma
  default is distinguished from an arbitrary guessed default.
- Existing optional decoder side data is preserved by frame-property copying.
  This does not invent absent HDR metadata or implement additional Dolby trims.
- Reconstruction math, filtering and output packing are unchanged.

The FFmpeg HEVC parser change is intentional: it exports the selected picture's
VUI properties into the context provided to av_parser_parse2. No software pixel
decoder is added. qsv_dovi.h and qsvdec.c are private FFmpeg source changes;
the public shared-library ABI remains unchanged.

## Validation so far

- CPU tests: BL metadata survives reordered output and SPS changes; key/token
  regression tests pass; 32 EL snapshots survive reverse output, EAGAIN,
  duplicate/invalid submissions and seek/reset boundaries.
- FFmpeg and Kodi SDK builds passed with four workers, 4 GiB memory limits and
  no swap/OOM. FFmpeg export, SONAME and dependency checks passed.
- Actual-stream header-only preflight passed: BL 3840x2160, EL 1920x1080,
  both native 10-bit, top-left chroma, limited range, BT.2020/PQ and square pixels.
  No decoder was opened, no GPU accessed, and Kodi/source were unchanged.
- One matched Saving Private Ryan dual-QSV frame capture passed, with actual
  mapped BL/EL evidence and the new FFmpeg/VPL runtime verified. Automatic
  restoration of the working build, override and library maps passed.
- That frame's canonical whole RGB picture and Dolby payload exactly match the
  retained qualified output; decoded-source timestamps and metadata match.
  Only validated transport ID/CRC fields are normalized, with alpha excluded.
- This is one-frame equality, not whole-playback cadence or efficiency evidence.

## Contents and application

`qsv-complete-frame-handoff.patch` applies the Kodi changes to the retained
renderer-display-owner candidate. `source-manifest.json` and the preparation
controller record its exact source pins. FFmpeg replacements are `qsv_dovi.h`,
`qsvdec.c` and `hevc/parser.c`; retain the corresponding SDK baseline/config.
Full modified Kodi source files are included for inspection.

`check_chroma_cpu.sh` runs the three C regression tests in the pinned FFmpeg CPU
test environment: /candidate holds these sources, /opt/ffmpeg-source holds the
configured baseline FFmpeg static libraries and headers. Tests explicitly keep
assertions enabled. Build controllers retain host-memory and cgroup safeguards;
their workstation paths are deployment-specific, not a portable build promise.

`handoff_metadata_probe.c` includes this exact FEL source and requires its matching
dvbridge_fel.h plus the built FFmpeg libraries. It reads a bounded number of
container packets and reports only header properties, never pixels or RPU bytes.

No film frames, extracted layers, RPU payloads or private capture artifacts are
published in this directory.
