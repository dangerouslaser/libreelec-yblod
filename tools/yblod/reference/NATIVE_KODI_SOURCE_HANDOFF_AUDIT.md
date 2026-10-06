# Kodi custom VAAPI source handoff: candidate boundaries

The custom source is a public-property snapshot, not a fabricated FFmpeg
hardware frame. Only the explicit experimental build and runtime value `1`
capture it. The ordinary decoder path keeps its existing lock order and scope.
The snapshot copies actual source timestamps, time base, chroma location,
format, dimensions, surface identifier, flags, colour fields and complete
expanded Dolby metadata bytes. It owns no original decoder buffer or private
FFmpeg reference. No unspecified chroma location is replaced with a default.

The actual render picture is acquired by an AVBuffer ownership token. It keeps
the real VA render-surface reservation until the native consumer completes.
The token validates the actual pool generation, display, surface and allocation
geometry. Native rendering and generation invalidation/destruction share Kodi's
graphics lock. An uncertain retained transaction marks the actual pool and a
process-sticky VA quarantine gate; native retries, new VA allocations/decodes
and inherited video fallback are rejected. Restart is required. Ordinary GUI
and existing presentation-fence behavior are not redefined by this contract.
If native cleanup cannot complete, bridge reset/destruction skips its own raw
GL/VPP resource cleanup rather than recycling uncertain resources. Quarantine
is process-restart-only, not a supported device-reset/display-loss recovery
procedure; this candidate does not promise continued playback after it.

## Idle borrowed-display lifetime in this actual producer

This conclusion is specific to the inspected Kodi/FFmpeg source, not a generic
claim that arbitrary VA displays may be borrowed indefinitely:

- `xbmc/cores/VideoPlayer/DVDCodecs/Video/VAAPI.cpp`: the successful
  `CVAAPIContext` is a process-lifetime singleton. `Release` removes the decoder
  and updates a diagnostics-only reference count; it does not delete/reset the
  singleton or terminate its VA display. Its only `vaTerminate` call handles
  failed initialization. Decoder cleanup destroys its own surfaces/configuration,
  not the successful singleton display.
- `xbmc/windowing/gbm/OptionalsReg.cpp`: the VA proxy obtains the display from
  the actual DRM render-node descriptor. Its destructor does not terminate the
  display. Ordinary window changes retain that render node.
- Actual FFmpeg 9.0.2 `libavutil/hwcontext_vaapi.c`: device uninitialization frees
  its format table. Display termination is in the owned-device free callback
  installed by device creation/derivation. Kodi instead allocates a device
  context, assigns the existing display and initializes it; it does not install
  that owned-display callback. Dropping this external-device reference therefore
  does not terminate the singleton display.
- `xbmc/windowing/gbm/WinSystemGbmGLESContext.cpp`: final window-system destruction
  ends/resets the DV bridge before delegating to EGL/window-system destruction.
  The ordinary EGL window-change path destroys a surface, not the surviving
  EGL context or VA render-node display.

Consequently an idle native context's VA scaler may retain its own resources
between frames for this producer without pinning a decoded frame indefinitely.
It must still be destroyed before actual display teardown. This audit does not
extend to an externally replaced display, device removal or a different player.

## Configuration changes and outer fallback

The native submission contract checks actual BL/EL dimensions, display and
chroma policy against the immutable context settings before GPU work. A changed
stream cannot silently reuse the old scaler configuration: rejection destroys
the old idle native context before the valid inherited route is considered.
Normal bridge reset also destroys the native context.

The DV branch of `CLinuxRendererGLES::Render` returns before its ordinary YUV
rendering branch, so a DV failure cannot fall through to legacy YUV sampling.
The custom renderer returns handled-without-new-video-draw when its lease is
invalid or quarantined, both before and after the window bridge call. This does
not increment the native presentation counter or claim a new frame was shown.

Compilation and review are not playback, performance or colour-accuracy evidence.
