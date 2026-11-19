# yblod-engine/docs

What each document about the Dolby Vision pipeline is, here and next to
the code it describes. A **current** document says what is true now.
**Reference** is material to look things up in, including the notices
that came with CroqueMr's Intel DV for LibreELEC (now
[libreelec-CB1](https://github.com/CroqueMr/libreelec-CB1)), imported into
`intel-dv/` on 2026-10-04. A **history** document is finished: it opens
with a status line saying so and what replaced it, and is otherwise left as
written. Sections cut from a current document are in a `history/` folder
next to it under the same file name. Code, kernel patches and licence files
cite some of these files by path: keep their paths. The distribution's
documents are in [yblod/docs](../../yblod/docs/README.md).

## Current

| File | What |
|---|---|
| [../README.md](../README.md) | what yblod-engine holds, and its CPU tests |
| [../vk/README.md](../vk/README.md) | the Vulkan engine: its C API, each output and how it was checked |
| [../integration/README.md](../integration/README.md) | Kodi's side: the adapter, the `native-dv.env` switches, what is still to be checked on a display |
| [intel-dv/OUTPUT-MODES.md](intel-dv/OUTPUT-MODES.md) | Settings > Player > Dolby Vision: every output and setting, how each was checked, its cost |
| [intel-dv/HARDWARE.md](intel-dv/HARDWARE.md) | what each output needs from the GPU, the connector and the TV |
| [intel-dv/ARCHITECTURE.md](intel-dv/ARCHITECTURE.md) | how a picture goes from the file to the TV, and who does what |
| [intel-dv/DIAGNOSTICS.md](intel-dv/DIAGNOSTICS.md) | what kodi.log records about Dolby Vision, `dv-diagnostics` |
| [intel-dv/PLAYBACK-HEALTH.md](intel-dv/PLAYBACK-HEALTH.md) | the periodic playback health line |
| [intel-dv/CHANGES.md](intel-dv/CHANGES.md) | the kernel and FFmpeg patches and the files they change; where the Kodi patches are described |

## Reference

| File | What |
|---|---|
| [../SOURCES.md](../SOURCES.md) | the host C's sources and what was taken from where; installed with the engine |
| [intel-dv/LICENSING.md](intel-dv/LICENSING.md) | the licensing notes that came with the import |
| [intel-dv/ORIGIN.md](intel-dv/ORIGIN.md) | the source credits that came with the import |
| [intel-dv/releases/](intel-dv/releases/) | CroqueMr's release notes from v0.1.0-rc1 to R0.3.0, as imported |
| [../tools/accuracy/README.md](../tools/accuracy/README.md) | the tools that measured the output against Dolby hardware |

## History

| File | What |
|---|---|
| [intel-dv/VALIDATION.md](intel-dv/VALIDATION.md) | validation of R0.2.1a-opt1 and R0.3.0, and of the converter routes (0.3.4, 0.3.5); kept at its path |
| [intel-dv/history/CHANGES.md](intel-dv/history/CHANGES.md) | sections cut from CHANGES.md: R0.2.1a-opt1 and R0.3.0, the libplacebo patches, the Kodi file index of 0.5.0 |
| [intel-dv/history/UPSTREAM-README.md](intel-dv/history/UPSTREAM-README.md) | CroqueMr's README at R0.3.0 |
| [intel-dv/history/BUILD.md](intel-dv/history/BUILD.md) | building CroqueMr's R0.3.0 overlay |
| [intel-dv/history/INSTALL.md](intel-dv/history/INSTALL.md) | installing R0.3.0 |
| [intel-dv/history/VERSIONS.md](intel-dv/history/VERSIONS.md) | the inputs of R0.3.0 |
| [intel-dv/history/SOURCE-BUNDLE.md](intel-dv/history/SOURCE-BUNDLE.md) | R0.3.0's source bundle |
| [intel-dv/history/CHANGELOG.md](intel-dv/history/CHANGELOG.md) | CroqueMr's changelog to R0.3.0 and Kodi 22.0 RC1 |
| [history/ACCURACY.md](history/ACCURACY.md) | the OpenCL engine measured against Dolby hardware (0.2) |
| [history/BUILD-VALIDATION.txt](history/BUILD-VALIDATION.txt) | a build check of the OpenCL engine's library (2026-10-09) |
| [history/ASYNC-PACK-20261010.txt](history/ASYNC-PACK-20261010.txt), [GUI-CACHE-20261010.txt](history/GUI-CACHE-20261010.txt), [GUI-REVISION-20261010.txt](history/GUI-REVISION-20261010.txt) | experiments on the OpenCL engine's GUI overlay (2026-10-10) |
| [history/NATIVE-PROFILE-20261010.txt](history/NATIVE-PROFILE-20261010.txt), [OSD-EXPLORATION-20261010.txt](history/OSD-EXPLORATION-20261010.txt) | profiling of the OpenCL engine on the N150 (2026-10-10) |
| [history/YBLOD-DISPLAY-COORDINATION-VALIDATION.txt](history/YBLOD-DISPLAY-COORDINATION-VALIDATION.txt) | the HDR and refresh-rate change before the first picture (2026-10-10) |
| [history/YBLOD-L5-OVERLAY-VALIDATION.txt](history/YBLOD-L5-OVERLAY-VALIDATION.txt) | L5 under the GUI, on the OpenCL engine (2026-10-10) |
| [history/YBLOD-SDR-RESTORE-VALIDATION.txt](history/YBLOD-SDR-RESTORE-VALIDATION.txt) | the SDR signal back after Dolby Vision (2026-10-10) |
| [history/YBLOD-LIVE-STARTUP-VALIDATION.txt](history/YBLOD-LIVE-STARTUP-VALIDATION.txt), [YBLOD-LIVE-SINGLE-OPEN-VALIDATION.txt](history/YBLOD-LIVE-SINGLE-OPEN-VALIDATION.txt), [YBLOD-LIVE-AUDIO-PREROLL-VALIDATION.txt](history/YBLOD-LIVE-AUDIO-PREROLL-VALIDATION.txt), [YBLOD-LIVE-ZAP-MEASUREMENTS.txt](history/YBLOD-LIVE-ZAP-MEASUREMENTS.txt) | live TV start: the changes in kodi-9908 and their measurements (2026-10-10) |
| [../integration/history/README.md](../integration/history/README.md) | sections cut from the integration README: the OpenCL engine's Kodi port and its qualification (0.2 to 0.3) |
| [../integration/history/QUALIFICATION-20261009.txt](../integration/history/QUALIFICATION-20261009.txt) | qualification of that port on the N150 (2026-10-09) |
| [../integration/history/STARTUP-HANDOFF-20261009.txt](../integration/history/STARTUP-HANDOFF-20261009.txt) | the black Dolby Vision frame before the film's first (2026-10-09) |
| [../integration/history/PRE2-20261009.txt](../integration/history/PRE2-20261009.txt), [PRE3-20261009.txt](../integration/history/PRE3-20261009.txt) | 0.2-pre2 packaging checks and the pre3 menu fix (2026-10-09) |
| [../integration/history/GUI-REVISION-FLICKER-20261010.txt](../integration/history/GUI-REVISION-FLICKER-20261010.txt) | the A/B test that left GUI revision reuse off (2026-10-10) |
| [../integration/history/MEASUREMENTS.md](../integration/history/MEASUREMENTS.md) | two OpenCL-era adapters compared (2026-10-09) |
| [../vk/history/README.md](../vk/history/README.md) | sections cut from the engine's README: its import from big-fella's dv-engine-vk and the sync of 2026-11-01 |
| [../vk/history/SYNC-2026-10-27.md](../vk/history/SYNC-2026-10-27.md), [SYNC-2026-10-27b.md](../vk/history/SYNC-2026-10-27b.md) | the engine's changes for Kodi, recorded for the sync back (2026-10-27) |
| [../vk/history/SYNC-2026-11-08.md](../vk/history/SYNC-2026-11-08.md) | the HDR10 output's import (2026-11-08) |
