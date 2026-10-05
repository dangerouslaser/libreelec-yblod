# Repeated capture of one paused SK4 picture

## Question and current status

We are checking whether our SK4 reference capture is repeatable before treating
small differences from it as errors in our renderer. Earlier comparisons found
an alternating-row difference in one colour channel. This experiment checks the
capture itself; it does not change the picture or tune our output to match it.

**Overlay-containing and overlay-free runs are complete.** Each run produced six
byte-identical physical reads across three fresh capture cycles. The second run
has no visible Kodi overlay and is associated with source frame 1943, not frame
1960. It was captured with the GUI framebuffer plane temporarily disabled.
Memory synchronization remains unverified in both runs. A successful tool exit
alone is not a colour-accuracy result.

## What the experiment does

The operator starts the numbered test video, pauses on a clearly identified
picture, and leaves the display connected and on until capture finishes. The
script never plays, pauses or seeks the video. It requires the existing
3840×2160, 24 Hz standard Dolby Vision output and an idle capture engine.

For each of three cycles, the script starts the existing VDIN loopback capture,
freezes a completed buffer, checks its freshly reported address and size, and
reads that same frozen buffer twice. It then stops the capture engine before
starting the next cycle. The address may be reused; a new capture is identified
by its cycle and fresh driver events, not by a supposedly unique address.

The two checks answer different questions:

- Same-buffer rereads: do two reads of one frozen buffer return the same bytes?
- Fresh captures: does the paused picture return the same bytes after restarting
  the capture engine?

All reads are bounded and read-only. The script records paused playback state,
driver timestamps, file hashes and all repeated metadata checks. It rejects
unfinished buffers, changed playback state and ambiguous or stale driver logs.
On exit it verifies capture has stopped, restores the original capture-memory
setting, and records whether that cleanup succeeded. No video precision,
dithering, bypass or picture settings are changed.

## Driver-dump limitation

The strict default requires a driver-produced dump before physical-memory
reads. The reviewed driver implementation synchronizes device-written memory
on this path, but the deployed SK4 accepted the dump command without creating
a file. Source inspection shows that the dump implementation is conditional
on build options; the exact reason on this installed kernel remains unverified.
Earlier captures without a saved driver dump do not establish that this
synchronization happened.

`--allow-unverified-dma-sync` explicitly permits this missing-file condition.
It still attempts the dump and records its absence. It does **not** tolerate a
short dump, overwrite an existing file, or invent a driver/readback comparison.
Both physical reads remain saved, using separate read-only synchronous mappings.

In this mode, matching reads show repeatable observed bytes, but **cannot rule
out stale cached data**. The word `complete` describes the capture procedure
and empirical readback checks, not verified cache synchronization or correct
Dolby processing. If a driver dump is available, it is retained and independently
compared with the first physical read; that evidence is reported separately.

## Reproducing the capture and analysis

These commands assume the scripts from `tools/yblod/reference/` have been copied
to the SK4 and the operator has already paused the test picture. Use a new
output directory each time. Do not run while another VDIN1 capture is active.

Strict device-side capture:

```sh
python3 /storage/capture_repeat.py /storage/repeat-NEW-RUN --cycles 3
```

Explicit diagnostic fallback when the driver dump is unavailable:

```sh
python3 /storage/capture_repeat.py /storage/repeat-NEW-RUN --cycles 3 \
  --allow-unverified-dma-sync
```

The capture directory contains `capture-repeat.json`, fresh driver-state logs,
and two raw reads per cycle, plus any available driver dumps. Allow about
150 MB for six raw reads or 224 MB including three driver dumps. Preserve the
whole directory when transferring it to the analysis machine. Raw video frames
stay outside the public repository; publish the code and aggregate reports.

Create a separate `identity.json` with these operator-verified fields:

| Field | Meaning |
| --- | --- |
| `source_sha256` | SHA-256 of the exact source video file. |
| `visible_frame_number` | Integer counter visibly shown in the paused picture. |
| `pts_us` | Integer source-frame presentation timestamp, in microseconds, independently associated with that counter. |

Do not fill these fields by guessing from a Kodi seek response or driver PTS.
Those values are useful state records, not an independent frame-number oracle.
Keep the identifying evidence with the private capture bundle.

On the analysis machine, from the repository root:

```sh
python3 tools/yblod/reference/compare_repeats.py \
  /path/to/repeat-NEW-RUN/capture-repeat.json \
  --identity /path/to/identity.json \
  --active-rectangle LEFT TOP RIGHT BOTTOM \
  --report /path/to/NEW-repeat-comparison.json
```

Replace the uppercase rectangle tokens with the checked integer boundaries of
the active picture; right and bottom are exclusive. Left and right must be even.
The rectangle must exclude the embedded metadata slots and any non-picture
border. Do not choose a rectangle because it makes the errors smaller.

The analyzer requires NumPy. It reads 32 rows at a time, verifies file sizes
and hashes, checks all three copies of each metadata packet and the supported
colour matrices, and independently compares all raw bytes. It separates changes
in embedded metadata from changes in the selected active picture. Picture
differences are reported for intensity (`I`) and two colour channels (`P`, `T`),
including even and odd rows counted from the full frame. Positive differences
mean the later read or cycle is higher than the earlier one.

Run the focused checks without accessing hardware:

```sh
python3 -m unittest discover -s tools/yblod/reference -p test_capture_repeat.py
python3 -m unittest discover -s tools/yblod/reference -p test_compare_repeats.py
```

## Reading the result

- Different same-buffer rereads undermine interpretation of differences between
  fresh captures. Investigate readback stability before blaming the renderer.
- Identical rereads with changing fresh captures establish observed variation
  between capture cycles, not its cause. Metadata-only changes are not picture
  changes. A changing picture does not by itself prove temporal dithering.
- Identical fresh captures establish repeatability for this paused picture and
  setup. They do not exclude a fixed alternating-row pattern, spatial dithering,
  a systematic capture error, or stale data when synchronization is unverified.
- This is an internal loopback capture, not an independent measurement of the
  HDMI wire or of the TV's displayed colours. It cannot certify Dolby accuracy.

No offset fitting, pixel correction or winner selection is performed.

## Findings — first run contains Kodi's pause overlay

The capture run completed three cycles. All six physical-read files have the
same capture-side recorded SHA-256:

```text
76f27eda66d98a240066977fb65f699764f9861aac2b17ffe480037019b9e00d
```

The [independent comparison report](results/repeat-comparison-1960-osd.json)
rehashes the files and confirms exact byte equality for all three same-buffer
pairs and both fresh-cycle pairs (cycle 0 against cycles 1 and 2). Every pair
has **zero changed bytes**. All active-picture channel differences are zero,
including the separate even- and odd-row groups. Embedded metadata is also
unchanged: all three copies of both packets pass their checksums and agree.
The analyzer's supported colour-matrix checks pass.

This establishes empirical repeatability of the observed bytes in this run.
**No driver dump was available in any cycle**, so there is no independent
driver-dump comparison and memory synchronization remains unverified. These
identical reads cannot rule out stale cached data.

The overview identifies visible frame counter **1960**, with **81.748 seconds**
shown in the test picture, but also shows Kodi's pause clock/progress overlay.
That overlay is part of the captured output. These files must not be used as
a clean frame-1960 reference to judge reconstruction accuracy or colour errors.
The report's identity records the source-file SHA-256 and visible counter, and
uses `81748000` microseconds. The saved source extraction manifest independently
confirms source packet 1960 at PTS `81748` with time base `1/1000`, and its source
SHA-256 matches the numbered file. Neither association relies on driver PTS.
The selected active rectangle is `[0, 275, 3840, 1884]` (right/bottom exclusive).
Full-frame byte equality is not dependent on that rectangle.

The saved provenance records unchanged paused playback checks, confirmed capture
shutdown and restoration of the original capture-memory setting (`0`). The
report includes the capture script and analyzer implementation hashes. Analysis
took **3.60 seconds**, with peak resident memory **49,412 KiB** and no swapping.

The result above addresses this overlay-containing capture only. The follow-up
below checks a separately identified paused picture without the overlay; no
video-precision tuning or fitted output correction was applied.

The broader reference test suite passed **282 tests**, plus **8 accuracy-tool
tests**, on Ollie, with reported
peak resident memory of **48,588 KiB** and no swapping for that test run. This is
software-test evidence, not a measurement of capture fidelity or live playback
performance.

## Findings — overlay-free GUI-plane-disabled run

The second run visibly shows **frame 1943 / 81.039 seconds**, without Kodi's
clock, pause label or progress bar. Source packet 1943 has PTS `81039` in the
Matroska `1/1000` time base, independently checked with `ffprobe`. This is not
a recapture of frame 1960 and must not be scored against that frame's renderer
output. The source SHA-256 is unchanged.

The [independent report](results/repeat-comparison-1943-gui-disabled.json)
confirms all three same-buffer pairs and both fresh-cycle pairs have **zero
changed bytes**, zero active I/P/T differences on both row parities, and matching
valid copies of both metadata packets. All six files have SHA-256:

```text
3f5bbdaee217bcc244bdb9a6cef4bd6e5947191143cf02c559f60f11e5f2823a
```

Analysis took **4.03 seconds**, peaked at **49,200 KiB** resident memory and did
not swap. Capture shutdown and original CMA-setting restoration succeeded.
Driver dumps remain unavailable, so identical observed bytes still cannot rule
out stale cache data or a systematic capture error. The different image/hash
from the first run does not independently prove cache coherency.

### Removing the GUI overlay

The installed framebuffer identifies itself as `mesondrmfb`. The capture
prototype temporarily wrote `1` to `/sys/class/graphics/fb0/blank` and restored
`0` in `finally`. The initial restore-to-visible basis was the previously visible
Kodi GUI, not an empty read from the `blank` attribute. We visually checked the
captured picture after the GUI restoration write and then stopped playback.

The applicable [DRM framebuffer source](https://github.com/CoreELEC/common_drivers/blob/4dbe1c27ae176fde4c1cbef7506618fd7f62b976/drivers/drm/meson_fbdev.c#L596)
disables the framebuffer's corresponding plane, not the whole display controller.
This supersedes the prototype's initial generic OSD-handler source assumption.
Successful writes do not prove hardware state; the clean preview is the evidence
that the GUI was absent. The HDMI/Dolby configuration and paused-player checks
stayed unchanged. Removing graphics is nevertheless a composition-state change,
so this run is labelled **GUI-plane-disabled**, not an untouched hardware pipeline.

The exact historical prototype is retained as
[capture-clean-prototype-20261005.py](results/capture-clean-prototype-20261005.py),
and its original orchestration record as
[gui-plane-orchestration-1943.json](results/gui-plane-orchestration-1943.json).
The report records their SHA-256 values and the corrected backend source basis.
Raw captures and identifying video previews remain private.

For future runs, use the reusable wrapper with an explicit visible-GUI check:

```sh
python3 /storage/capture_clean.py /storage/CLEAN-NEW-RUN \
  --confirm-visible-gui --allow-unverified-dma-sync
```

Copy both `capture_clean.py` and `capture_repeat.py` to the same device directory.
This wrapper requires the reviewed `mesondrmfb` backend, records hide/restore
attempts, and saves capture files under `CLEAN-NEW-RUN/capture/`. It does not
change playback. Its default still requires a driver dump unless the diagnostic
fallback is explicitly selected. Visually verify the captured frame and absence
of overlays before making source-frame comparisons.

The next processing comparison must use the reconstructed source frame **1943**.
Stable rereads weaken an observed-temporal-variation explanation for this paused
picture, but do not exclude fixed spatial processing or systematic readback errors.
Do not convert repeatability into a claim that either device's output is correct.

The new reusable GUI-plane wrapper has **11 additional stdlib tests**, covering
confirmation/backend rejection, restoration on capture errors and partial hide
failure, paused-state changes, and unsuccessful restoration reporting.
