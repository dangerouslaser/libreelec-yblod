# Changes by component and file

What YBLOD changes in each component it patches. Patches apply in file-name
order within each component, through the links in `projects/Generic/patches/`.
The upstream's R0.2 and R0.3 sections, the libplacebo patches and the Kodi
series' former file index are in [history/CHANGES.md](history/CHANGES.md).

## linux

One series, applied in file name order through the links in
`projects/Generic/patches/linux/`. The files live in `yblod-engine/patches/linux/`
(Dolby Vision, HDR10+ and the HDMI link fixes the tunnel needs) and
`yblod/patches/linux/` (QMS, FreeSync and general HDMI changes). Each is `git
format-patch` output; its header says what it does, where it came from and what
it was tested on. Until 0.4.1 the series was 30 files (`linux-9900-00` to
`linux-9933`); the regrouping changed no code. The series is for Linux 7.4-rc3
(until 2026-11-18, 7.3.4; see `yblod/docs/KERNEL-74-20261118.txt`).

| Patch | Purpose |
| --- | --- |
| [linux-9900-video-hdmi-dolby-vendor-infoframes.patch](../../patches/linux/linux-9900-video-hdmi-dolby-vendor-infoframes.patch) | Dolby vendor InfoFrames in the HDMI helpers: the Dolby-OUI form and the HDMI 1.4b form. |
| [linux-9901-i915-dolby-vision-tunnel.patch](../../patches/linux/linux-9901-i915-dolby-vision-tunnel.patch) | i915: the Dolby Vision tunnel on native HDMI (connector properties, link and scanout policy, EDID parser, tunnel formats, rejection messages). |
| [linux-9910-i915-hdmi-qms.patch](../../../yblod/patches/linux/linux-9910-i915-hdmi-qms.patch) | i915: HDMI 2.1 Quick Media Switching (refresh rate changes without a blank). |
| [linux-9912-i915-hdmi-spd-source-type.patch](../../../yblod/patches/linux/linux-9912-i915-hdmi-spd-source-type.patch) | i915: the SPD InfoFrame says "Digital STB", so TVs do not treat the input as a PC. |
| [linux-9913-hdmi-link-robustness.patch](../../patches/linux/linux-9913-hdmi-link-robustness.patch) | i915, amdgpu: a short HPD drop is not an unplug; the sink's SCDC is checked again after a hotplug. |
| [linux-9920-amdgpu-dolby-vision-tunnel.patch](../../patches/linux/linux-9920-amdgpu-dolby-vision-tunnel.patch) | amdgpu: the Dolby Vision tunnel on native HDMI, with i915's properties and policies. |
| [linux-9922-amdgpu-avi-itc-no-data.patch](../../../yblod/patches/linux/linux-9922-amdgpu-avi-itc-no-data.patch) | amdgpu: AVI InfoFrame ITC=0 for content type No Data. |
| [linux-9923-hdr-10bpc-ycbcr420.patch](../../../yblod/patches/linux/linux-9923-hdr-10bpc-ycbcr420.patch) | amdgpu, i915: HDR at 4K50/60 as 10 bpc YCbCr 4:2:0 instead of 8 bpc RGB. |
| [linux-9924-amdgpu-dcn10-black-background.patch](../../../yblod/patches/linux/linux-9924-amdgpu-dcn10-black-background.patch) | amdgpu: DCN 1.x blends against black, not green, on YCbCr links. |
| [linux-9925-amdgpu-hdmi-freesync-without-vcp-code.patch](../../../yblod/patches/linux/linux-9925-amdgpu-hdmi-freesync-without-vcp-code.patch) | amdgpu: HDMI TVs without an MCCS VCP code stay FreeSync/VRR-capable on Linux 7.4 (`amdgpu.freesync_hdmi_vcp`). |
| [linux-9930-i915-dolby-vision-dp-hdmi-converter.patch](../../patches/linux/linux-9930-i915-dolby-vision-dp-hdmi-converter.patch) | i915: Dolby Vision through an onboard DP-to-HDMI converter (INUC 11). |
| [linux-9931-i915-dolby-vision-lspcon-level-shifter.patch](../../patches/linux/linux-9931-i915-dolby-vision-lspcon-level-shifter.patch) | i915: Dolby Vision through the NUC7's MCDP2800 LSPCON in level-shifter mode. |
| [linux-9932-drm-hdr10plus-metadata.patch](../../patches/linux/linux-9932-drm-hdr10plus-metadata.patch) | DRM core, HDMI helpers, i915, amdgpu: HDR10+ dynamic metadata (`HDR10PLUS_METADATA`). |
| [linux-9933-i915-hdmi-freesync.patch](../../../yblod/patches/linux/linux-9933-i915-hdmi-freesync.patch) | i915: FreeSync over HDMI on QMS's rate changes. |

The table below covers the files of the Intel Dolby Vision tunnel (`linux-9900`,
`linux-9901`).

| Changed source file | High-level change |
| --- | --- |
| `drivers/gpu/drm/i915/display/intel_atomic.c` | Expose/read/write the per-connector DV property in atomic state. |
| `drivers/gpu/drm/i915/display/intel_display.c` | Validate byte-preserving scanout and reject incompatible display processing. |
| `drivers/gpu/drm/i915/display/intel_display_params.c` | `i915.enable_dv_lab`: the tunnel's switch, on by default; 0 removes the connector properties. |
| `drivers/gpu/drm/i915/display/intel_display_params.h` | Default the dedicated LE image to automatic capability detection. |
| `drivers/gpu/drm/i915/display/intel_display_types.h` | Store DV property and transport state on the Intel connector. |
| `drivers/gpu/drm/i915/display/intel_dv_lab_policy.h` | Validate EDID, modes and native-HDMI topology, including level shifters. |
| `drivers/gpu/drm/i915/display/dvbridge_edid.h` | Validate complete EDIDs and Standard-DV versions using the same parser as Kodi. |
| `drivers/gpu/drm/i915/display/intel_hdmi.c` | Connect hardware eligibility, HDMI timing and signaling. |
| `drivers/video/hdmi.c` | Initialize, validate, pack and unpack the HDMI DV vendor information frame. |
| `include/linux/hdmi.h` | Define the HDMI DV signaling fields shared by the driver helpers. |

## ffmpeg

| Patch | Purpose |
| --- | --- |
| [ffmpeg-9900-dovi-rpu-extension-block-bytes.patch](../../patches/ffmpeg/ffmpeg-9900-dovi-rpu-extension-block-bytes.patch) | Preserve extended Dolby Vision metadata during decoding and carry it to the player (`dovi_rpudec.c`, `dovi_meta.h`). |
| [ffmpeg-9901-mov-dav1-sample-entry.patch](../../patches/ffmpeg/ffmpeg-9901-mov-dav1-sample-entry.patch) | Recognize Dolby Vision AV1 tracks in MP4 containers. |
| [ffmpeg-9902-dovi-rpu-aligned-padding.patch](../../patches/ffmpeg/ffmpeg-9902-dovi-rpu-aligned-padding.patch) | Accept RPUs that carry a zero padding byte before the CRC32 when the payload ends byte-aligned (backport of upstream FFmpeg 5e95a3ddfbdb). |

| Changed source file | High-level change |
| --- | --- |
| `libavcodec/dovi_rpudec.c` | Retain parsed extension bytes so the output stage can preserve CM4 metadata; accept the aligned padding byte before the CRC32. |
| `libavformat/isom_tags.c` | Recognize the dav1 MP4 sample entry for DV AV1 tracks. |
| `libavutil/dovi_meta.h` | Carry validated original extension bytes alongside parsed metadata. |

## kodi

One series on Kodi `22.0rc2-Piers`: `kodi-9900` to `kodi-9910` and
`kodi-9990` in `yblod/patches/kodi/`, `kodi-9950` to `kodi-9968` in
`yblod-engine/patches/kodi/`. [KODI-PATCHES.md](../../../yblod/docs/KODI-PATCHES.md)
says what each patch does and where the older patches named in this
repository's history went; each file's message says what it changes. The
HDMI retry changes and the diagnostics are in kodi-9953; the diagnostics'
counters never drive playback decisions.

## LibreELEC recipes

`packages/mediacenter/kodi/package.mk` builds Kodi with `-DENABLE_DVBRIDGE=ON`,
depends on `yblod-engine-vk` and declares GPL-3.0-or-later only for x86_64
Generic on GBM with OpenGL ES and Vulkan; every other build is Kodi as
upstream, with the patches. Kodi does not link libplacebo, and the
libplacebo recipe is LibreELEC's. The other recipes and glue files are listed
in [yblod/README.md](../../../yblod/README.md).

## Kernel diagnostics in Kodi

`kodi-9953-dv-display-drm-and-diagnostics.patch` includes the background logging hook:

- `DRMAtomic.cpp`: request kernel evidence only after a bounded DV output failure.
- `DVBridgeKernelLog.h`: parse kernel records; exclude userspace, stale, duplicate and unrelated messages.
- `DVBridgeKernelLogReader.h`: read the kernel ring without blocking rendering or clearing the system log.

`DVBRIDGE_DIAGNOSTICS=0` disables the added Kodi supplement. The separate
compatibility/recovery patches are unaffected. See [DIAGNOSTICS.md](DIAGNOSTICS.md).
