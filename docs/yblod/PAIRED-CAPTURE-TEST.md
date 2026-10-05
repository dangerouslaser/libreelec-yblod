# Same-frame conversion comparison

This diagnostic saves the release and experimental output from the **same
decoded base layer, enhancement layer, and source metadata**. It compares the
conversion paths without seeking two playbacks to approximately the same time.
It does not establish which picture is more accurate; that still needs an
independent reference.

## Safety and scope

- Off by default. Kodi must start with `DVBRIDGE_CAPTURE_PAIRS=1` to enable it.
  With it off there is no request-file polling, capture allocation, or readback.
- One request saves one pair, about 64 MiB, under a new private directory in
  `/storage/dvbridge-captures`. Existing captures are not overwritten.
- Requires full-screen, unrotated, native 3840x2160 Dolby Vision with an
  enhancement layer and no subtitles/GUI composition. Other frames leave the
  request pending. Quick Sync enhancement-only mode is supported.
- A separate renderer renders both alternatives before the real screen output.
  It cannot commit its metadata to the presentation renderer. Both outputs must
  confirm the requested conversion path before a completion record is written.
- Capturing blocks for GPU readback and disk writes and may visibly stutter.
  Do not measure performance during this test. Do not continuously request frames.
- A failed request is consumed, logged, and may leave partial files. Only a
  directory with `pair.json` is a completed pair. The capture refuses to start
  with less than 256 MiB of free disk space.

## Temporary activation

Create a runtime-only systemd drop-in for `kodi.service` containing:

```ini
[Service]
Environment=DVBRIDGE_CAPTURE_PAIRS=1
```

Use `/run/systemd/system/kodi.service.d/90-dvbridge-capture.conf`, reload systemd,
and restart Kodi. The setting disappears at reboot. Create the capture root
directory before requesting a frame. Play one of the test titles, disable
subtitles, seek, and wait for the playback controls to disappear. Then create an
empty `/storage/dvbridge-captures/request` file. Its contents are ignored.

The next eligible frame produces a `pair-XXXXXX` directory containing:

- `release.rgba` and `direct.rgba`: 3840x2160 RGBA8 Dolby Vision transport bytes,
  **not ordinary viewable RGB images**. Row orientation is detected by metadata.
- `metadata.bin`: the exact FFmpeg `AVDOVIMetadata` input blob; tied to this build's
  FFmpeg layout, not an independently portable RPU bitstream.
- `pair.json`: input timestamps in the renderer's native units, Quick Sync mode,
  applied colour offset, active-area margins, and output metadata packet count.
- `request`: the consumed request marker.

Record the title, requested seek, actual player time and image build separately.
The player clock and decoder timestamp can have different origins.

## Comparison

On a machine with NumPy installed:

```sh
python3 tools/yblod/accuracy/test_compare_pair.py
python3 tools/yblod/accuracy/compare_pair.py /path/to/pair-XXXXXX
```

The tool validates every output metadata packet's CRC and requires identical
metadata between paths. It excludes the metadata-bearing rows and the blanking
margins, then reports I, P, and T differences in native 12-bit codes. It does not
shift the images, remove a fitted bias, or convert/clamp the output to RGB.
Large disagreements must be located and checked against a reference before
calling either path more accurate. Small code differences are not by themselves
a perceptual visibility test.

After testing, remove only the runtime capture drop-in, reload systemd, and
restart Kodi (or reboot). Restore the viewer's subtitle preference. Preserve
the captures separately from public source-control commits.
