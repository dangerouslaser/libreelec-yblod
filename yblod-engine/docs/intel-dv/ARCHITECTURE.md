# Architecture

```text
Kodi VideoPlayer → FFmpeg / VAAPI → owned frame metadata + paired BL/EL surfaces
                → Vulkan engine (libdv_engine_vk.so.1) → one of two private
                  scanout buffers: the DV tunnel (RGB 8-bit) or HDR10 (12-bit 4:2:2)
                → Kodi GBM atomic presentation (+ tunnel format, HDR metadata)
                → Intel/AMD DRM/KMS → TV
```

## Responsibilities

- **FFmpeg** parses source metadata. The patch preserves extension bytes needed
  for CM4 and recognizes the AV1 DV container tag. It does not implement the
  complete HDMI transport or replace the television's display management.
- **The Vulkan engine** (`yblod-engine/vk`, big-fella's dv-engine-vk with
  YBLOD's additions) reconstructs each picture from the decoded VAAPI
  surfaces (FEL included; CB1 Master Reference's processing for unscaled
  pictures with Annex B upscaling), composes Kodi's GUI over it, serializes
  the frame's display metadata (optionally with CM4.0 levels) and writes the
  tunnel picture, or converts to HDR10 (the Master Reference conversion). It
  compiles YBLOD's host C from `yblod-engine/src` (tables, the metadata
  serializer, plan inputs) through its `build.rs`. It is YBLOD's only Dolby
  Vision renderer since 0.4.0; the OpenCL engine and the libplacebo
  compatibility renderer are gone.
- **Kodi** keeps its normal decoding, buffering, refresh-rate selection,
  controls and GUI. Its adapter (`CDVPrivateSource`, `CDVPrivateVulkan`)
  hands the engine each picture and the GUI (in place, as a dmabuf), owns the
  two scanout buffers' slots and pairs FEL surfaces by timestamp; the window
  commits the ready buffer with the tunnel's signal. The menu output
  (graphics-only frames with static metadata) is packed by Kodi on the GPU,
  not by the engine. The adapter is selected only for eligible source,
  decoder, display and transport combinations; if the engine cannot start,
  Dolby Vision titles play as plain base-layer video.
- **Display drivers** (i915/xe, amdgpu) advertise the connector controls
  (`DVBRIDGE_DV_STANDARD_LAB`, `DVBRIDGE_TUNNEL_FORMAT`), validate EDID and
  HDMI topology, construct signalling and reject display processing that
  could alter transport bytes.

The RGB8 framebuffer is a transport container, **not SDR output or an 8-bit
reduction of the reconstructed image**. Scaling, GUI composition and
active-area handling happen in the engine before the tunnel is packed. The
packed surface must not undergo ordinary color correction, dithering or
scaling afterwards.

## Safety and lifecycle

Metadata state is prepared separately from presentation. Failed atomic commits
cannot advance it as if a frame had been displayed. Seek/reset discards stale
layer pairing and metadata. Frames are submitted without waiting: the atomic
commit waits for the scanout buffer's fence, and the decoded surfaces stay
leased until the engine reports the frame done. The adapter captures and
restores display state; ending DV playback returns control to Kodi's normal
path. A picture the engine does not take is not shown (logged); there is no
fallback renderer.

Ordinary SDR/HDR playback and software metadata probes do not enter the DV
path. This does not remove the independent Intel HDR10 link-precision
correction included in the kernel patches; see the component change index.

## Deliberately unchanged

No external mpv process, launch wrapper, separate settings dialog,
private activation service, patched Mesa or modified Intel Media Driver.
LibreELEC's original settings addon and Kodi service remain upstream files.
Playback preferences are Kodi's own Settings > Player > Dolby Vision. The
optional Player information panel extends Estuary; the stock panel remains
available.

The low-level `enable_dv_lab` parameter and `DVBRIDGE_DV_STANDARD_LAB` property
retain their existing names because they are the kernel/userspace interface.
They are enabled by policy in this dedicated image and are not an end-user
activation menu. Renaming an interface solely for appearance would break
compatibility with existing clients and diagnostic tools.
