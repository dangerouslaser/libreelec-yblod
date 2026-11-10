# YBLOD Kodi adapter

The Kodi side of YBLOD's Dolby Vision output is the patch series in
`yblod-engine/patches/kodi/` (Kodi `e6192109`, linked into
`projects/Generic/patches/kodi/`). Since 0.4.0 it drives one renderer, the
Vulkan engine (`yblod-engine/vk`): `kodi-9999-yblod-29` (the Vulkan engine
without the OpenCL library, behaviour-neutral), `-30` (Vulkan only: the
OpenCL engine path and the libplacebo compatibility renderer removed), `-31`
(Dolby Vision -> HDR10 through the tunnel) and `-32` (the Dolby Vision menu).
The engine's adapter is `CDVPrivateSource` / `CDVPrivateVulkan`; the window
(`WinSystemGbmGLESContext`) commits its scanout buffers with the tunnel's
signal.

## Build and runtime

Use YBLOD's normal Generic x86-64 image build. Kodi's recipe depends on
`yblod-engine-vk` (the engine library, built with cargo and glslc), which also
installs `runtime.env` as `/usr/lib/kodi/native-dv.env`, the Kodi service
drop-in `20-native-dv.conf` and `dv-diagnostics`. Optional
`/storage/.config/native-dv.env` entries override the packaged values.
`runtime.env` holds only what the Vulkan path reads (audited from the code at
0.4.0); its comments name each variable's reader.

Kodi's Settings > Player > Dolby Vision applies its settings as environment
overrides at start and whenever a setting changes (`DVEngineSettings.h`); for
those the setting wins over `native-dv.env`. See
[OUTPUT-MODES.md](../docs/intel-dv/OUTPUT-MODES.md) for the menu and what
each entry sets. The hidden setting `yblod.build` (always true) lets skins
detect YBLOD with `System.GetBool(yblod.build)`; `dvbridge.settingsversion`
records the settings migrations done.

If the Vulkan engine cannot start (no library, another ABI, no Vulkan
device), Dolby Vision titles play as plain base-layer video until Kodi
restarts, with one notification and one log line; there is no second
renderer.

## History (0.2-0.3)

The sections below record the OpenCL engine's port and
qualification (Kodi `63063c8e`, 2026-10). They describe that engine, which
0.4.0 removed; the reports stay for reference.

## Current status

The complete Generic image has built and booted on the N150. The installed
engine has passed selected current-profile controls/recovery checks, and initial
GPU timestamp baselines are available in
[QUALIFICATION-20261009.txt](QUALIFICATION-20261009.txt). The reproduced early
P7 presentation gaps were subsequently fixed and retested in
[STARTUP-HANDOFF-20261009.txt](STARTUP-HANDOFF-20261009.txt), which also records
remaining controls-open frame drops in a 59.94 Hz sample. These results apply
to the exact images identified in each report. Pre2 packaging and final smoke
results are recorded in [PRE2-20261009.txt](PRE2-20261009.txt). A subsequent
visually reproduced VM menu-return defect and the pre3 target-recreation fix
are documented in [PRE3-20261009.txt](PRE3-20261009.txt); pre2's timing/signalling
checks did not establish correctness of the visible menu image.

The unchanged standalone source passes all three Release-mode CPU contract
tests with GCC 14.2 and CMake 4.4.4: specialization admission, geometry and
output-slot ownership. These are not GPU or Kodi playback tests.

The patch is `yblod-engine/patches/kodi/kodi-9999-yblod-03-native-source.patch`.
Generic builds apply it after the existing YBLOD QSV and menu patches and
install the engine and dependencies through Kodi's package recipe. This is
integration source; use the separately packaged pre-release for installation.

The subsequent `kodi-9999-yblod-04-native-startup.patch` establishes a valid
black DV signal before releasing playback startup. The final
`kodi-9999-yblod-05-remove-legacy-settings.patch` removes Quick Sync scaling and
Match Dolby hardware levels from the settings UI. Both legacy behaviors are
forced off, including for profiles with old saved values. This does not change
native reconstruction or disable hardware video decoding.

## Qualification boundaries

The report above records packaged-image profile, timing, reference, cold-cache,
EOF, ownership/recovery and menu/QMS smoke checks. These are bounded tests, not
all-media certification. The menu-off/passthrough P7 startup fix passed the
documented A/B and packaged-boot checks; 59.94 Hz controls-open playback still
requires work.
Optical menu appearance, transition blackout and physical audio synchronization
are not proven by driver readbacks. Pre-release testing is not general certification.

The route targets 3840x2160 progressive output with admitted source geometry
and metadata. HDR bitmap overlays and native composite screenshots remain
unsupported. Retired profiles are unsupported; profile 20 is deferred.
The existing engine tests are not independent Dolby conformance tests.

`MEASUREMENTS.md` is historical context comparing the prior and newer CB1
adapters. It is **not** a measurement of this YBLOD port.

The adapter code uses GPL-3.0-or-later; existing Kodi and bridge notices
remain applicable. See yblod-engine's LICENSE and SOURCES.md, installed with
the engine package.
