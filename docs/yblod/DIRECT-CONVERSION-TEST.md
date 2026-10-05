# Direct conversion experiment

This test removes the intermediate RGB PQ conversion from native-size TV-led
Dolby Vision playback. Decoding, BL reshaping, FEL reconstruction, Quick Sync,
chroma filters, hardware-level adjustment and HDMI metadata remain unchanged.
It is not yet an accuracy or performance claim.

## Compare

In Settings > Player > Videos > Dolby Vision, toggle **Direct Dolby Vision
conversion (experimental)**. Stop and restart the video after changing it.
Off is the release renderer; on requests the shortcut. The default is off.

The shortcut currently requires an unrotated 3840x2160 picture filling the
3840x2160 output, without overlays. Quick Sync enhancement-layer mode works;
the base-layer Quick Sync mode rotates the picture internally and therefore
uses the release path. Subtitles, menus, HDR10 output, smaller pictures and
other unsupported layouts also use the release path. A shortcut render error
retries the same frame on the release renderer and disables the experiment
until the next playback session.

Look in kodi.log for `DVBridge conversion:`. `active=direct-lms` confirms the
shortcut actually ran; `active=release-rgb` means the release path ran, even if
the setting is on. Closing an overlay can switch the shortcut back on.

Compare the same clips and frames with all other settings unchanged. Include
Profile 8.1 and Profile 7 FEL, dark detail, bright highlights and strong colors.
Check opening/closing subtitles and menus for flashes or color jumps. Record
the active path, Quick Sync setting and hardware-level adjustment with results.

## Implementation and checks

The libplacebo patch adds a separate transport-rendering entry point. Existing
entry points and public structure layouts are unchanged, so existing tools
such as dvfit retain their release behavior. The new Kodi binary needs the
matching library; install the complete test image, not Kodi alone. The new
transport entry point does not perform frame mixing.

The matrix is `(transport LMS from RGB) * (RGB from HPE LMS)`; the decoder then
applies the source RPU's linear matrix exactly once. It outputs PQ transport LMS,
not RGB. RGB color management is bypassed, and the existing output hook converts
the triplet to IPT and packs it. The original RGB clipping is intentionally
absent; differences in those regions require separate accuracy investigation.

Run `python3 tools/yblod/accuracy/test_direct_conversion.py` for double-precision
CPU math and source-wiring checks. These do not establish GPU accuracy, playback
performance, or HDMI correctness. Those require testing the image on hardware.

## Performance sampling

`tools/yblod/accuracy/measure_playback.py` runs on the test device. It reads
Kodi's CPU time and i915's per-client engine busy-time counters once per second,
deduplicating repeated file descriptors for the same GPU client. It does not
open a debug overlay or alter playback. Kodi's local JSON-RPC endpoint must be
available without authentication, as on this test VM.

For example, seek to 10:00, then run:

```
python3 measure_playback.py 1917-direct --at 610 --seconds 60 > 1917-direct.json
```

Repeat the same interval with the setting off, restarting the video to latch
the change. Keep subtitles off, Quick Sync unchanged and all overlays closed.
Check `DVBridge conversion:` in the log to confirm the requested path ran.
Reject measurements with changed GPU clients, paused playback, buffering or
fallback/overlay transitions. Repeat matched pairs to check run-to-run variation.

GPU busy percentage is occupied engine time, not FPS or wall-clock speedup.
CPU percentage is relative to one core. Video-engine totals can exceed 100%
when multiple engines are active. Dynamic GPU clocks and movie/network load
remain sources of variation; the saved samples include clock readings and
playback positions. Renderer failure counters are not dropped-frame counters.
