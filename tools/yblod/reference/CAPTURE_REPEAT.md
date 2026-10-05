# Repeated capture of one paused SK4 picture

## Question and current status

We are checking whether our SK4 reference capture is repeatable before treating
small differences from it as errors in our renderer. Earlier comparisons found
an alternating-row difference in one colour channel. This experiment checks the
capture itself; it does not change the picture or tune our output to match it.

**First capture and independent comparison completed.** Three capture cycles
produced six physical reads with identical bytes. However,
the overview shows Kodi's pause clock/progress overlay. This is useful evidence
of observed capture repeatability, not a clean reference for comparing the
video-processing pipelines. A clean capture is still needed. A successful tool
exit alone is not a colour-accuracy result.

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

The next capture should use the same visibly identified paused picture with
Kodi's overlay absent, then repeat the same checks without changing video
precision or fitting the output. Until that clean run is checked, the result
above addresses the repeatability of this overlay-containing capture only.

The broader reference test suite passed **282 tests**, plus **8 accuracy-tool
tests**, on Ollie, with reported
peak resident memory of **48,588 KiB** and no swapping for that test run. This is
software-test evidence, not a measurement of capture fidelity or live playback
performance.

Do not convert a repeatability result into a claim that either device's output
is correct. The next step depends on what actually changes and on which capture
limitations remain unresolved.
