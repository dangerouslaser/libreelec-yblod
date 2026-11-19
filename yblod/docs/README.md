# yblod/docs

What each document in yblod/docs is. A **current** document says what is
true now. **Reference** is material to look things up in. A **history**
document is finished (a plan carried out, a dated record that something
newer replaced): it opens with a status line saying so and what replaced
it, and is otherwise left as written. **Release records** are what each
release published; they are never edited. The engine's documents are in
[yblod-engine/docs](../../yblod-engine/docs/README.md).

Where things stand: YBLOD plays Dolby Vision with one engine, the Vulkan
engine in `yblod-engine/vk` (the OpenCL engine was removed in 0.4.0). Kodi
is `22.0rc2-Piers` with the patch series in KODI-PATCHES.md, the Generic
kernel Linux 7.4-rc3, and the LibreELEC base master `3a98afdd` of
2026-11-14.

## Current

| File | What |
|---|---|
| [../../README.md](../../README.md) | what YBLOD is and does, its settings, requirements and limits, installing |
| [../README.md](../README.md) | the repository's layout, the glue outside `yblod-engine/` and `yblod/`, building |
| [../tools/bench/README.md](../tools/bench/README.md) | the Kodi playback benchmark and functional checks |
| [../iphone-remote/README.md](../iphone-remote/README.md) | the iPhone remote and this image's side of it |
| [BRANCHES.md](BRANCHES.md) | branches and tags, moving to a newer LibreELEC, releasing, contributing to CroqueMr's libreelec-CB1 |
| [KODI-PATCHES.md](KODI-PATCHES.md) | the Kodi patch series: number ranges, what each patch does, where the patches before 0.5.0 went |
| [KERNEL-74-20261118.txt](KERNEL-74-20261118.txt) | the Generic kernel, Linux 7.4-rc3: how the recipe selects it, its configuration, each patch on it, CroqueMr's CB1 kernel patches triaged; the record of the move, history at the next one |
| [RESYNC-20261118.txt](RESYNC-20261118.txt) | the LibreELEC base, master `3a98afdd` of 2026-11-14: what the merge brought and kept; the record of the resync, history at the next one |

## Reference

| File | What |
|---|---|
| [KERNEL-PARAMETERS.md](KERNEL-PARAMETERS.md) | every kernel switch YBLOD's patches add, its default and how to set it |

## Release records

| File | What |
|---|---|
| [releases/](releases/README.md) | each release's notes and checks, and the data behind them |

## History

| File | What |
|---|---|
| [history/RESYNC-20261009.txt](history/RESYNC-20261009.txt) | the LibreELEC resync of 2026-10-09 (Kodi 63063c8e, Linux 7.2.9) |
| [history/YBLOD-PRE4-TEST3-DEPLOYMENT.txt](history/YBLOD-PRE4-TEST3-DEPLOYMENT.txt) | a test deployment of 0.2-pre4-test3 (2026-10-10) |
| [history/YBLOD-0.4.0-PLAN.md](history/YBLOD-0.4.0-PLAN.md) | the plan for 0.4.0: the Vulkan engine only, the HDR10 and HDR10+ conversions, CM4.0, the new menu (2026-11-09) |
| [history/SDR-OUTPUT-PLAN.md](history/SDR-OUTPUT-PLAN.md) | the plan for Convert to SDR and what was built (2026-11-11, shipped in 0.5.1) |
