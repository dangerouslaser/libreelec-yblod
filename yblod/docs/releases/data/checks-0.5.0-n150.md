# YBLOD 0.5.0-t2 on the N150: functional checks

Run on 2026-11-11/12 on the owner's Intel N150 (LG TV behind a Denon AVR),
image `yblod-0.5.0-t2` as bench profile `y050t2`, with
`yblod/tools/bench/checks.py` (what each check does and passes on is in
`yblod/tools/bench/README.md`). "Default" is the image as shipped
(`DV_PRIVATE_NONBLOCK=0`); "non-blocking" is the same profile with
`DV_PRIVATE_NONBLOCK=1`. The frame-time tables are in
`bench-0.4.1-vs-0.5.0-n150.md`. Raw files: Ollie,
`~/yblod-050/bench/results/y050t2*/checks/`.

Nobody looked at the TV. Everything below is a kernel flip trace, a
counter, a position or a log line; what only eyes can confirm is listed at
the end. "Inferred" marks a conclusion drawn from the code or from another
measurement instead of measured directly.

## Boot service

| | 0.4.1 | 0.5.0-t2 |
| --- | --- | --- |
| `yblod-dv-prepare`, cold cache (first boot of a fresh `/storage`) | 71 s | 185 s (184.8 s wall, 184.1 s CPU, 1.5 GB peak memory; pipeline cache 17.1 MB) |
| second boot | | skipped: 13 ms, 9 ms CPU, marker matches |

Kodi was at the first-run wizard while it ran.

## Verify output (`DVVK_VERIFY`)

`DVVK_VERIFY` cannot be set in `native-dv.env`: Kodi's "Verify output"
setting overwrites it when Kodi starts, with 60 (on) or 0 (off). The passes
therefore check every 60th frame. The engine prints its count every 120
checked frames, so a 24p pass plays 312 s; where a pass presented fewer
than 7200 frames the count is frames processed / 60 and "0 differed" means
no "differs from the reference" line was logged.

| Pass | Default: checked / differed | Non-blocking: checked / differed |
| --- | --- | --- |
| 1917, plain | 120 / 0 | 120 / 0 |
| Saving Private Ryan, plain | 120 / 0 | not run |
| 28 Years Later, plain | 120 / 0 | not run |
| Gemini Man, plain | 120 / 0 | 120 / 0 |
| 1917, OSD opened 10 s and closed 5 s, 21 times | 120 / 0 | 120 / 0 |
| Gemini Man, OSD opened and closed 9 times | about 76 / 0 | about 106 / 0 |
| 1917, generated subtitle (3 s on, 1 s off) | 120 / 0 | not run |
| Gemini Man, generated subtitle | about 90 / 0 | not run |
| 1917, 9 rounds of pause, 5 frame steps, resume, +/-30 s seek | 120 / 0 | 120 / 0 |
| 1917, "Convert to HDR10" | 120 / 120 "differ": not a valid check, see below | not run |

- With "Convert to HDR10" every checked frame differs in about 6.17 million
  pixels starting at row 276: exactly the active picture. Inferred from
  `engine.rs` (`record_reference` takes its pack from the Dolby Vision
  variants, never the mapped ones): the reference is the Dolby Vision
  output, so verify cannot check the HDR10 path and this says nothing about
  the HDR10 picture.

## Default configuration

| Check | Result | Evidence |
| --- | --- | --- |
| Pause | pass | 30 s paused, after the skin's seek bar has settled: 0 flips, 0.0 % GPU render busy, 2.9-3.2 W package (1917, Gemini Man, Saving Private Ryan, 28 Years Later). In the first seconds after the pause the seek bar animates: 83 flips (1917) and 196 (Gemini Man) between 2 s and 9 s after it. The matrix's paused scenario (pause, then a seek): 0.7 % and 1.0 % GPU against 46.8 % and 75.0 % on 0.4.1. |
| Resume | pass | first flip 62-144 ms after the request; every gap 1 at 24p afterwards; Gemini Man as before the pause. A 1.5 s pause and resume: the same. No surface pool reset. |
| Frame step, Gemini Man (60p) | pass | 10 steps (`PlayerControl(FrameAdvance(1))`): one flip each, position +16 or 17 ms each. |
| Frame step, 24p (1917, Saving Private Ryan, 28 Years Later) | oddity | The position moves 41-42 ms with every step, but the first two or three steps flip no new picture and one later step in ten flips none. Traced on 28 Years Later with `DV_PRIVATE_ENDPOINT_TRACE=1`: two more pictures are committed after the pause request; steps 1-3 commit nothing; then one picture per step, with one picture never shown; resume skips two. The same with `DV_PRIVATE_SKIP_REPEATS=0`, so the hold of repeated pictures is not the cause. Not measurable on 0.4.1, which commits every refresh. |
| Seeks, 1917 and Saving Private Ryan | pass | +30 s, -30 s, +10 min, -10 min, next chapter, previous chapter, absolute, -10 s on each: 0 "decoded surfaces come from a new pool" resets, no FEL message, 0 dropped and 0 skipped frames, positions as asked, flips never stopped for more than 0.21 s (the seek bar keeps the display flipping, so this is not the time to the first new picture), every gap 1 afterwards. |
| Surface pool resets | pass | 0 in 60 matrix passes and in every check; exactly 1 in the title sequence, where 1917 is opened over Saving Private Ryan without a stop (the engine is kept and reset). |
| OSD and subtitles: unchanged GUI skipped | pass | Frames that scanned the GUI again, of the frames profiled (`DVVK_PROFILE`): 1917 plain 0 of 360, OSD open 243 of 480, OSD closed 0 of 360, subtitle on 10 of 480 (the cue's changes), OSD toggled twice 25 of 360. Gemini Man: 0 of 720, 80 of 600, 0 of 720, 10 of 840, 54 of 720. With `DV_PRIVATE_GUI_UNCHANGED_SKIP=0` a subtitle scans 95-120 of 120. GUI state (`Window.IsVisible(videoosd)`, `VideoPlayer.SubtitlesEnabled`) as asked at every probe. |
| 24p on the menu's 60 Hz mode | pass | "adjust display refresh rate" off, 1917: 60.004 Hz, 23.972 pictures/s, flip gaps 3 2 3 2 (719 and 726), 0 dropped, 0 skipped, 17.63 ms GPU per picture (17.3-17.7 at 24 Hz), 2123 frames rendered in the 88 s pass (one per picture) and 1067 repeats held. A rendering commit takes two refreshes at 60 Hz, which leaves about half a held refresh per picture. |
| Titles in a row | pass | Airplane! (SDR 1080p), 1917, Alien (HDR10), Gemini Man, Airplane!, 28 Years Later, Saving Private Ryan, 1917 opened over it. SDR and HDR10: VAAPI, 23.97 flips/s, every gap 1, no engine, passthrough audio; HDR10 signalled `hdr_blob=429 colorspace=9 max_bpc=12`, SDR `hdr_blob=0`. Each Dolby Vision title: `dv=1`, the engine started, 0 dropped and 0 skipped. Open to playing 2.1-3.3 s by the driver's polling. |
| Logs | pass | 60 matrix passes in each mode: no error line; the same three warnings as 0.4.1 in the same numbers ("OutputPicture - timeout waiting for buffer" 58 in 42 passes, `MSGQ_NOT_INITIALIZED` 7 and 8 against 6, the Pulseaudio passthrough note 4). No engine failure, no recovery, no failed commit. The kernel log of the whole session (7 h 16 min, both modes): one i915 line, the framebuffer compression note at boot. |

## Non-blocking presentation (`DV_PRIVATE_NONBLOCK=1`)

The author's checklist (`yblod-engine/integration/README.md`), with
`DV_PRIVATE_FLIP_TRACE=1` for the checks and without it for the matrix:

| Item | Result | Evidence |
| --- | --- | --- |
| Flips queued, in order | pass | Three scanout buffers. In 24,778 traced flips (pause, seek, OSD and subtitle checks on 1917, Gemini Man and Saving Private Ryan): the vertical blank time always increases and the same framebuffer never flips twice running. |
| `busy`, `timeouts`, `flip-pending`, failed commits | pass | 247,800 flips queued over both matrix repetitions and all checks: `busy=0 timeouts=0`; no "flip-pending", no "atomic commit failed", no out-fence error, nothing from DRM in the kernel log. |
| `blocking` only at transitions | pass | 326 blocking commits in the whole session. The count rises by three per title in the window runs and the checks (start, refresh change, stop) and stays where it is through every measured window and through the pause, step, seek, OSD and subtitle checks. |
| 24p: every refresh a new picture | pass | 1917 steady: 599 of 600 on time in the first summary; queued to vertical blank 42.6 ms mean, 43.1 ms max. Matrix: every gap 1 on all three 24p films in every scenario. |
| 60p: every refresh a new picture | **fail** | Gemini Man: 56.0 flips/s of 59.94; 235-240 of 3385 flips per minute take two refreshes (0.4.1 and default: 40.5/s, gaps 1 2 1 2). 0-1 dropped, 0 skipped. See below. |
| FEL with the OSD open | pass | 1917 and Saving Private Ryan: 23.98 flips/s, every gap 1, 0 dropped, 0 skipped (default: 21.2 and 21.6/s; 0.4.1: 20.8 and 19.2/s). |
| Pause, steps, resume, seeks | pass | As default: 0 flips and 0.0 % GPU paused; steps at 60p flip once each (two of ten flipped none in this run, the position moved every time); the 24p step oddity is unchanged; 16 seeks with 0 pool resets and no FEL message. |
| Start time | pass | 0.99-1.12 s, as default (0.4.1: 1.20-1.63 s). |
| Latency | as designed at 24p; not shown at 60p | "Private source startup latency" `cachetotal`: 1917 208.5 ms against 166.8 ms default (one 41.7 ms refresh more). Gemini Man: 100.0 ms in both modes, a floor, so this number does not show the extra 16.7 ms refresh at 60p. Debug log, 75 s of each film in each mode: one "ActiveAE::SyncStream" adjustment at the start (default 28.1 ms and 10.0 ms, non-blocking 15.7 ms and 24.7 ms), no audio discontinuity afterwards in either. |
| 24p on the menu's 60 Hz mode | pass | 59.998 Hz, 23.976 pictures/s, gaps 2 and 3 (719 and 725), 0 dropped, 0 skipped, 17.40 ms GPU per picture, 3178 repeats held for 2117 pictures. The flip summary counts nearly every flip `late` here (3596 of 3600): its test is "one refresh after the flip before", which a 24p picture on 60 Hz never is. |
| Verify output | pass | see the table above: 0 frames differed. |

### Why Gemini Man does not reach 59.94 fps

Measured (engine deadline trace and a kernel trace of `i915_request_add`
and `dma_fence_signaled`, 6 s, in
`y050t2-nb-trace/checks/raw/gemini-deadline-trace` and `gemini-ktrace`):

- Each frame is submitted about 1 ms after a vertical blank and its flip is
  queued one refresh later. Its GPU work starts 4-20 ms after submission
  (`queue_ms`) and takes 11.9 ms. The start delay grows by about 1.2 ms
  every two frames; when the work ends later than the next vertical blank
  the flip takes two refreshes (queued to vertical blank 33 ms instead of
  16.7 ms), the delay falls back and the cycle starts again, about every
  16th flip.
- The render requests (the engine) and the video requests (the decoder)
  never overlap: every render request completes 12.1 ms (11.4-12.4) after
  the previous completion of either kind, and a video request 5.4 ms after
  it. Two pictures cost 2 x 12.1 + 2 x 5.4 = 35 ms of serialized GPU work
  against 33.4 ms of display time.
- On 1917 (`1917-ktrace`) video requests do complete while a render request
  runs: the two engines can work in parallel on this GPU.
- The engine's own trace reports `decode_waits: 0` for every frame.

Inferred: on Gemini Man the engine's and the decoder's requests wait for
each other through implicit fences on the decoded surfaces, in the kernel
and not through the engine's semaphores. If they ran in parallel, 12 ms of
engine work would fit a 16.7 ms refresh. Which buffer carries the
dependency was not established.

## Found on the way

| | What | Since |
| --- | --- | --- |
| Subtitles switched off while a line shows | Kodi's GUI cache stays `empty=false` and the engine keeps composing a non-empty GUI (pack 6.0 ms instead of 4.6 ms on 1917, 13.7 instead of 11.6 on Gemini Man) until the OSD is opened and closed. Switched off between two lines: `empty=true`, pack 4.6 ms. Inferred: the last line stays in the GUI buffer, probably on screen. | Not from 0.5.0's skip: the same with `DV_PRIVATE_GUI_UNCHANGED_SKIP=0` (and then 23.3 ms per frame instead of 18.9). 0.4.1 not tested. |
| Saving Private Ryan, 1:53:46-1:54:00 | Five "Vulkan engine range check failed pts=... flags=0x1 (already presented)" errors in 14 s of film, with and without verify. Presentation is unaffected (23.97/s, every gap 1). | 0.4.1 has the same check and message; that passage was not played on 0.4.1. |
| A title opened over a FEL title | One warning from the title that ends: "Dolby Vision FEL: the enhancement layer lost its pairing (the stream ended before a common key frame)". The new title plays normally. | New message of 0.5.0. |
| Kodi's dropped-frame counter, 60p, non-blocking | Higher although more pictures are presented: OSD 766-777 against 184-186 (41.7 against 29.7 flips/s), subtitle 188-189 against 2 (51.6 against 39.6), HDR10 output 177-192 against 73-78 (46.5 against 34.0). | Non-blocking only. Not explained. |
| HDR10 output on two more films (one repetition) | Saving Private Ryan 26.45 ms per frame default and 26.37 non-blocking (Dolby Vision output: 23.07); 28 Years Later 12.45 and 13.27 (11.86), at GPU clocks of 764 and 698 MHz. 23.94-23.98 flips/s, 0 dropped. | New measurement; no 0.4.1 figure. |
| LibreELEC boot | "FAT-fs (mmcblk0p3): Volume was not properly unmounted": LibreELEC mounts big-fella's FAT partition. Nothing was written there by these tests. | Not looked at on 0.4.1. |

## For eyes on the TV

1. Gemini Man with non-blocking on: is 56 pictures/s with one doubled
   refresh about every quarter second better to watch than 0.4's steady
   40.5/s?
2. Audio and video in step with non-blocking on (one refresh more latency,
   compensated on paper), on a 24p and on the 60p title.
3. The picture after a seek, a chapter skip and a title opened over another:
   the right film, no picture of the old one (the pool reset counts are
   right; a missed pool change cannot be seen in a counter).
4. Subtitles switched off while a line is showing: does the line stay?
5. Frame step at 24p: the first steps after a pause show nothing new.
6. OSD and subtitle over the video: complete, nothing stale, with both
   presentation modes (verify found no differing frame, but it reads the
   same GUI buffer the engine does).
7. Saving Private Ryan around 1:53:50: anything visible where the range
   check fails?
8. SDR and HDR10 titles look as on 0.4.1 (their signal and cadence are).

Not tested: HDR10+ output, an EDID change or hotplug during playback, a GPU
hang, AMD, QMS behaviour (the mode and signal lines are the same as 0.4.1).
