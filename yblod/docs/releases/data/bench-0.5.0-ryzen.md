# Kodi playback benchmark

Made by `yblod/tools/bench/report.py`; the method and every definition are in `yblod/tools/bench/README.md`. A cell is the median of the repetitions, the lowest and highest repetition in brackets. `(!)`: a repetition failed one of its checks (listed at the end).

| image | profile's native-dv.env | version | kernel | CPU | GL | recorded (UTC) | display |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ryzen-y050` | `DVBRIDGE_DIAGNOSTICS=1` | yblod-0.5.0 | 7.3.0 | AMD Ryzen 5 3500U with Radeon Vega Mobile Gfx | OpenGL ES 3.2 Mesa 26.2.5 | 2026-11-12T16:00:11+00:00 | unattended run: TV power state not observed; HDMI sink LG TV SSCR2 connected directly (no AVR) |
| `ryzen-y050-nb` | `DVBRIDGE_DIAGNOSTICS=1 DV_PRIVATE_NONBLOCK=1` | yblod-0.5.0 | 7.3.0 | AMD Ryzen 5 3500U with Radeon Vega Mobile Gfx | OpenGL ES 3.2 Mesa 26.2.5 | 2026-11-12T17:29:33+00:00 | unattended run: TV power state not observed; HDMI sink LG TV SSCR2 connected directly (no AVR) |

## Films

What Kodi and the engine said each stream is (first image; the layer from the engine's log in scenario P: FEL has a reconstruction stage, a MEL's enhancement layer is not decoded, Profile 8 has none).

| film | title | passage from | stream | enhancement layer | fps | audio | output mode |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1917 | 1917 (2019) | 0:30:40 | profile=7 level=6 compatibility=6 size=3840x2160 | FEL | 23.976 | (codec: truehd, channels: 8, sample rate: 48000, pass-through) | 3840x2160 clock_khz=296703 totals=5500x2250 |
| spr | Saving Private Ryan (1998) | 1:49:40 | profile=7 level=6 compatibility=6 size=3840x2160 | FEL | 23.976 | (codec: truehd, channels: 8, sample rate: 48000, pass-through) | 3840x2160 clock_khz=296703 totals=5500x2250 |
| 28yl | 28 Years Later (2025) | 0:30:40 | profile=8 level=6 compatibility=1 size=3840x2160 | none | 23.976 | (codec: eac3, channels: 6, sample rate: 48000, pass-through) | 3840x2160 clock_khz=296703 totals=5500x2250 |
| gemini | Gemini Man (2019) | 0:30:40 | profile=7 level=9 compatibility=6 size=3840x2160 | MEL (not decoded) | 59.94 | (codec: truehd, channels: 8, sample rate: 48000, pass-through) | 3840x2160 clock_khz=593407 totals=4400x2250 |

## Frame time and presentation

GPU render time per presented picture (ms; the headline) and per source frame (the same unless pictures are missing), pictures presented per second, Kodi's dropped/skipped frames around the window, and the flips that were not one source frame after the one before ("late").

| film | scenario | ryzen-y050 ms/frame | ryzen-y050 ms/source frame | ryzen-y050 fps | ryzen-y050 drop/skip | ryzen-y050 late | ryzen-y050-nb ms/frame | ryzen-y050-nb ms/source frame | ryzen-y050-nb fps | ryzen-y050-nb drop/skip | ryzen-y050-nb late |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1917 | plain | 14.66 (14.65-14.68) | 14.66 (14.65-14.67) | 23.97 (23.97-23.97) | 0 / 0 | 0 | 14.65 | 14.66 | 23.99 | 0 / 0 | 0 |
| spr | plain | 18.68 (18.68-18.68) | 18.68 (18.68-18.69) | 23.98 (23.98-23.99) | 0 / 0 | 0 | 18.64 | 18.64 | 23.98 | 0 / 0 | 0 |
| 28yl | plain | 4.08 | 4.07 | 23.97 | 0 / 0 | 0 | 4.11 | 4.11 | 23.98 | 0 / 0 | 0 |
| gemini | plain | 6.82 | 6.82 | 59.92 | 0 / 0 | 1 | 6.85 | 6.85 | 59.94 | 0 / 0 | 0 |
| 1917 | OSD open | 22.39 | 22.41 | 23.99 | 0 / 0 | 0 | 22.33 | 22.34 | 23.98 | 0 / 0 | 0 |
| spr | OSD open | 20.91 | 20.91 | 23.98 | 0 / 0 | 0 | 20.88 | 20.88 | 23.98 | 0 / 0 | 0 |
| 28yl | OSD open | 5.18 | 5.18 | 23.97 | 0 / 0 | 0 | 5.46 | 5.46 | 23.98 | 0 / 0 | 0 |
| gemini | OSD open | 9.99 | 9.28 | 55.66 | 22 / 0 | 257 | 9.91 | 9.70 | 58.65 | 22 / 9 | 76 |
| 1917 | subtitle | 14.91 | 14.91 | 23.98 | 0 / 0 | 0 | - | - | - | - | - |
| gemini | subtitle | 7.20 | 7.17 | 59.71 | 0 / 0 | 13 | - | - | - | - | - |
| 1917 | DV to HDR10 | 14.72 | 14.72 | 23.98 | 0 / 0 | 0 | - | - | - | - | - |
| gemini | DV to HDR10 | 7.97 | 7.97 | 59.93 | 0 / 0 | 1 | 7.97 | 7.97 | 59.92 | 0 / 0 | 1 |

## Change against ryzen-y050

The same numbers as a difference from the first image: GPU time per source frame (the work a second of film costs, whatever was presented), GPU time per presented picture, and pictures presented per second. A frame-time difference under 3 % is noise (see the spread table).

| film | scenario | ryzen-y050-nb ms/source frame | ryzen-y050-nb ms/frame | ryzen-y050-nb fps |
| --- | --- | --- | --- | --- |
| 1917 | plain | +0.0 % | -0.1 % | 23.97 to 23.99 |
| spr | plain | -0.3 % | -0.2 % | 23.98 to 23.98 |
| 28yl | plain | +0.9 % | +0.9 % | 23.97 to 23.98 |
| gemini | plain | +0.5 % | +0.5 % | 59.92 to 59.94 |
| 1917 | OSD open | -0.3 % | -0.3 % | 23.99 to 23.98 |
| spr | OSD open | -0.1 % | -0.1 % | 23.98 to 23.98 |
| 28yl | OSD open | +5.5 % | +5.4 % | 23.97 to 23.98 |
| gemini | OSD open | +4.5 % | -0.8 % | 55.66 to 58.65 |
| 1917 | subtitle | - | - | - |
| gemini | subtitle | - | - | - |
| 1917 | DV to HDR10 | - | - | - |
| gemini | DV to HDR10 | -0.1 % | -0.1 % | 59.93 to 59.92 |

## Flip gaps

Gaps between flips in refresh periods, summed over the repetitions (`1: n` only is perfect), and the display's refresh rate.

| film | scenario | ryzen-y050 gaps (Hz) | ryzen-y050-nb gaps (Hz) |
| --- | --- | --- | --- |
| 1917 | plain | 1: 2884 (23.975) | 1: 1444 (23.976) |
| spr | plain | 1: 2888 (23.975) | 1: 1444 (23.976) |
| 28yl | plain | 1: 1441 (23.976) | 1: 1442 (23.976) |
| gemini | plain | 1: 3609, 2: 1 (59.94) | 1: 3611 (59.94) |
| 1917 | OSD open | 1: 1444 (23.976) | 1: 1444 (23.976) |
| spr | OSD open | 1: 1444 (23.976) | 1: 1444 (23.976) |
| 28yl | OSD open | 1: 1441 (23.976) | 1: 1442 (23.976) |
| gemini | OSD open | 1: 3099, 2: 257 (59.94) | 1: 3462, 2: 74, 3: 2 (59.94) |
| 1917 | subtitle | 1: 1443 (23.976) | - |
| gemini | subtitle | 1: 3586, 2: 13 (59.94) | - |
| 1917 | DV to HDR10 | 1: 1443 (23.976) | - |
| gemini | DV to HDR10 | 1: 3612, 2: 1 (59.94) | 1: 3609, 2: 1 (59.94) |

## CPU, GPU clock and power

Kodi's render (main) thread and whole process in % of one core, the GPU's actual clock while awake (MHz, not pinned), package power (W, RAPL).

| film | scenario | ryzen-y050 render thread % | ryzen-y050 process % | ryzen-y050 GPU MHz | ryzen-y050 W | ryzen-y050-nb render thread % | ryzen-y050-nb process % | ryzen-y050-nb GPU MHz | ryzen-y050-nb W |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1917 | plain | 3.1 (3.1-3.2) | 21.4 (20.4-22.4) | 573 (556-590) | 12.9 (12.8-13.1) | 2.9 | 20.7 | 556 | 12.8 |
| spr | plain | 3.9 (3.8-4.0) | 20.4 (20.1-20.8) | 684 (675-692) | 15.4 (15.3-15.4) | 3.5 | 21.2 | 641 | 15.4 |
| 28yl | plain | 2.6 | 12.7 | 353 | 8.1 | 2.2 | 12.2 | 327 | 8.2 |
| gemini | plain | 6.1 | 28.9 | 700 | 16.9 | 5.0 | 27.4 | 751 | 16.8 |
| 1917 | OSD open | 5.6 | 24.1 | 742 | 16.3 | 5.2 | 23.0 | 759 | 16.4 |
| spr | OSD open | 5.3 | 22.2 | 717 | 16.8 | 4.8 | 21.3 | 700 | 17.1 |
| 28yl | OSD open | 3.8 | 13.8 | 403 | 8.7 | 3.5 | 13.7 | 412 | 8.8 |
| gemini | OSD open | 9.8 | 33.5 | 861 | 19.6 | 9.9 | 33.3 | 883 | 20.2 |
| 1917 | subtitle | 3.9 | 22.7 | 590 | 13.5 | - | - | - | - |
| gemini | subtitle | 7.8 | 32.1 | 734 | 17.1 | - | - | - | - |
| 1917 | paused | 1.3 | 7.9 | 200 | 7.3 | - | - | - | - |
| gemini | paused | 2.8 | 9.4 | 208 | 7.9 | - | - | - | - |
| 1917 | DV to HDR10 | 3.3 | 23.0 | 564 | 13.2 | - | - | - | - |
| gemini | DV to HDR10 | 6.4 | 28.3 | 776 | 18.5 | 5.2 | 26.7 | 785 | 19.2 |

## Paused

60 s paused on a film frame: GPU render busy (% of wall time) and pictures flipped per second.

| film | ryzen-y050 GPU busy % | ryzen-y050 flips/s | ryzen-y050 render thread % | ryzen-y050-nb GPU busy % | ryzen-y050-nb flips/s | ryzen-y050-nb render thread % |
| --- | --- | --- | --- | --- | --- | --- |
| 1917 | 0.5 | 0.43 | 1.3 | - | - | - |
| gemini | 0.7 | 1.10 | 2.8 | - | - | - |

## Playback start

Seconds from `Player.Open` to the first flip of uninterrupted presentation (median of the repetitions' medians; lowest and highest single start).

| film | ryzen-y050 start s | ryzen-y050-nb start s |
| --- | --- | --- |
| 1917 | 1.15 (1.15-1.15, n=3) | - |
| spr | 1.14 (1.10-1.19, n=3) | - |
| 28yl | 0.89 (0.88-0.94, n=3) | - |
| gemini | 1.19 (1.17-1.19, n=3) | - |

## The two frame-time sources

Plain playback: DRM fdinfo (ms per presented picture, all of Kodi's render work) against the engine's own GPU timestamps (`DVVK_PROFILE`, mean of the 120-frame means; worst p95 and maximum), taken in a separate pass.

| image | film | fdinfo, log off | fdinfo, log on | engine mean | engine p95 / max | engine vs fdinfo (same pass) |
| --- | --- | --- | --- | --- | --- | --- |
| ryzen-y050 | 1917 | 14.66 (14.65-14.68) | 14.65 | 14.05 | 15.33 / 16.35 | -4.1 % |
| ryzen-y050 | spr | 18.68 (18.68-18.68) | 18.68 | 18.12 | 21.04 / 23.85 | -3.0 % |
| ryzen-y050 | 28yl | 4.08 | 4.07 | 3.47 | 4.45 / 5.01 | -14.9 % |
| ryzen-y050 | gemini | 6.82 | 6.86 | 6.23 | 7.87 / 8.58 | -9.2 % |

## Run-to-run spread

Half the range between the repetitions as a share of the median, for the frame time. A difference between two images smaller than this is noise. The last rows pool plain playback with the engine-log passes (scenario P), which measure the same thing when the log costs nothing.

| film | scenario | ryzen-y050 repetitions (ms/frame) | ryzen-y050-nb repetitions (ms/frame) | ryzen-y050 +/- % | ryzen-y050-nb +/- % |
| --- | --- | --- | --- | --- | --- |
| 1917 | plain | 14.65, 14.68 | 14.65 | 0.1 | 0.0 |
| spr | plain | 18.68, 18.68 | 18.64 | 0.0 | 0.0 |
| 28yl | plain | 4.08 | 4.11 | 0.0 | 0.0 |
| gemini | plain | 6.82 | 6.85 | 0.0 | 0.0 |
| 1917 | OSD open | 22.39 | 22.33 | 0.0 | 0.0 |
| spr | OSD open | 20.91 | 20.88 | 0.0 | 0.0 |
| 28yl | OSD open | 5.18 | 5.46 | 0.0 | 0.0 |
| gemini | OSD open | 9.99 | 9.91 | 0.0 | 0.0 |
| 1917 | subtitle | 14.91 | - | 0.0 | - |
| gemini | subtitle | 7.20 | - | 0.0 | - |
| 1917 | DV to HDR10 | 14.72 | - | 0.0 | - |
| gemini | DV to HDR10 | 7.97 | 7.97 | 0.0 | 0.0 |
| 1917 | plain, with the engine-log passes | 14.65, 14.68, 14.65 | 14.65 | 0.1 | 0.0 |
| spr | plain, with the engine-log passes | 18.68, 18.68, 18.68 | 18.64 | 0.0 | 0.0 |
| 28yl | plain, with the engine-log passes | 4.08, 4.07 | 4.11 | 0.0 | 0.0 |
| gemini | plain, with the engine-log passes | 6.82, 6.86 | 6.85 | 0.3 | 0.0 |

## ryzen-fella (Vega 8) against the N150, 0.5.0

Box: ryzen-fella, AMD Ryzen 5 3500U, Radeon Vega 8 (Raven, DCN 1.0), 6 GB,
LG TV (SSCR2) directly on HDMI; bench profile `y050` = the published
0.5.0 standard edition (`11e1d1b570`). N150 numbers from
`bench-0.5.0-n150.json` (images `y050t2` / `y050t2-nb`, the 0.5.0
release candidate, two repetitions; the release image measured within
1.2 % of it). The owner shortened the run on ryzen-fella: default
settings = repetition 1 of the whole matrix plus repetition 2 of 1917 and
Saving Private Ryan plain; non-blocking = one repetition of scenarios A
and B for all four films and E for Gemini Man. Nobody watched the TV:
nothing here is about how the picture looks.

### Engine GPU time per frame (the engine's own timestamps, `DVVK_PROFILE`, scenario P)

Same metric on both boxes: the mean of the engine's `dvvk profile: gpu MEAN ms` lines inside the 60 s window (Vulkan timestamp queries around the engine's command buffers; no Kodi GUI drawing, no driver work outside them). Default settings.

| film | Vega 8 engine ms/frame | N150 engine ms/frame | Vega 8 / N150 |
| --- | --- | --- | --- |
| 1917 | 14.052 | 17.523 (17.299-17.747) | 0.80 |
| spr | 18.125 | 23.078 (23.063-23.094) | 0.79 |
| 28yl | 3.467 | 11.980 (11.768-12.193) | 0.29 |
| gemini | 6.230 | 11.554 (11.547-11.561) | 0.54 |

### Kodi playback, default

`ms/pic`: GPU busy time of `kodi.bin`'s DRM clients per presented picture, from fdinfo (Vega 8: `drm-engine-gfx`; N150: `drm-engine-render`). The two drivers account busy time differently, so compare these across boxes with care; within a box they are comparable. `pics/s`: page flips per second from the kernel's `drm_vblank_event_delivered` tracepoint (same on both). Median of the repetitions, range in brackets.

| film | scenario | Vega 8 ms/pic | N150 ms/pic | Vega 8 pics/s | N150 pics/s |
| --- | --- | --- | --- | --- | --- |
| 1917 | plain | 14.66 (14.65-14.68) | 17.53 (17.34-17.72) | 23.97 (23.97-23.97) | 23.98 (23.97-23.98) |
| spr | plain | 18.68 (18.68-18.68) | 23.07 (23.04-23.10) | 23.98 (23.98-23.99) | 23.97 (23.97-23.98) |
| 28yl | plain | 4.08 | 11.86 (11.76-11.95) | 23.97 | 23.98 (23.98-23.98) |
| gemini | plain | 6.82 | 11.60 (11.60-11.60) | 59.92 | 40.52 (40.51-40.53) |
| 1917 | OSD open | 22.39 | 27.73 (27.61-27.85) | 23.99 | 21.22 (20.91-21.53) |
| spr | OSD open | 20.91 | 31.13 (31.11-31.15) | 23.98 | 21.55 (21.40-21.70) |
| 28yl | OSD open | 5.18 | 12.32 (12.14-12.49) | 23.97 | 23.98 (23.97-23.98) |
| gemini | OSD open | 9.99 | 18.60 (18.57-18.63) | 55.66 | 29.70 (29.66-29.75) |
| 1917 | subtitle | 14.91 | 18.38 (18.35-18.41) | 23.98 | 23.98 (23.98-23.98) |
| gemini | subtitle | 7.20 | 13.25 (13.25-13.26) | 59.71 | 39.60 (39.60-39.61) |
| 1917 | DV to HDR10 | 14.72 | 19.01 (18.84-19.18) | 23.98 | 23.97 (23.97-23.98) |
| gemini | DV to HDR10 | 7.97 | 14.84 (14.84-14.85) | 59.93 | 33.96 (33.91-34.00) |
| 1917 | plain, engine timing log on | 14.65 | 17.54 (17.32-17.77) | 23.98 | 23.97 (23.97-23.97) |
| spr | plain, engine timing log on | 18.68 | 23.07 (23.06-23.08) | 23.98 | 23.98 (23.98-23.98) |
| 28yl | plain, engine timing log on | 4.07 | 12.01 (11.80-12.22) | 23.98 | 23.97 (23.97-23.98) |
| gemini | plain, engine timing log on | 6.86 | 11.61 (11.60-11.61) | 59.93 | 40.46 (40.39-40.52) |

### Kodi playback, non-blocking (`DV_PRIVATE_NONBLOCK=1`)

`ms/pic`: GPU busy time of `kodi.bin`'s DRM clients per presented picture, from fdinfo (Vega 8: `drm-engine-gfx`; N150: `drm-engine-render`). The two drivers account busy time differently, so compare these across boxes with care; within a box they are comparable. `pics/s`: page flips per second from the kernel's `drm_vblank_event_delivered` tracepoint (same on both). Median of the repetitions, range in brackets.

| film | scenario | Vega 8 ms/pic | N150 ms/pic | Vega 8 pics/s | N150 pics/s |
| --- | --- | --- | --- | --- | --- |
| 1917 | plain | 14.65 | 17.48 (17.27-17.69) | 23.99 | 23.98 (23.97-23.98) |
| spr | plain | 18.64 | 23.17 (23.09-23.24) | 23.98 | 23.98 (23.97-23.98) |
| 28yl | plain | 4.11 | 12.12 (12.10-12.15) | 23.98 | 23.97 (23.97-23.98) |
| gemini | plain | 6.85 | 11.86 (11.86-11.87) | 59.94 | 56.01 (55.98-56.05) |
| 1917 | OSD open | 22.33 | 28.35 (28.34-28.36) | 23.98 | 23.98 (23.98-23.98) |
| spr | OSD open | 20.88 | 31.08 (31.07-31.09) | 23.98 | 23.97 (23.96-23.98) |
| 28yl | OSD open | 5.46 | 12.84 (12.80-12.89) | 23.98 | 23.98 (23.98-23.99) |
| gemini | OSD open | 9.91 | 18.75 (18.73-18.76) | 58.65 | 41.74 (41.72-41.77) |
| gemini | DV to HDR10 | 7.97 | 15.00 (14.99-15.00) | 59.92 | 46.50 (46.45-46.55) |

## Non-blocking presentation: Kodi's flip counters

`DV_PRIVATE_NONBLOCK=1` in `/storage/.config/native-dv.env`, Kodi
restarted; put back to the profile's line (`DVBRIDGE_DIAGNOSTICS=1`)
afterwards. Kodi's `DV flips queued=` line (every 600 queued flips,
cumulative since Kodi started, so each row includes the rows above it and
the warm-up passes); the last line of each measured pass:

| run | queued | on time | late | blocking | busy | timeouts | flip gaps in the window | Kodi drop / skip |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1917 plain | 4200 | 4197 | 3 | 5 | 0 | 0 | 1: 1444 | 0 / 0 |
| spr plain | 8400 | 8395 | 5 | 11 | 0 | 0 | 1: 1444 | 0 / 0 |
| 28yl plain | 12600 | 12593 | 7 | 17 | 0 | 0 | 1: 1442 | 0 / 0 |
| gemini plain | 22800 | 22791 | 9 | 23 | 0 | 0 | 1: 3611 | 0 / 0 |
| 1917 OSD | 27000 | 26988 | 12 | 29 | 0 | 0 | 1: 1444 | 0 / 0 |
| spr OSD | 31200 | 31186 | 14 | 35 | 0 | 0 | 1: 1444 | 0 / 0 |
| 28yl OSD | 35400 | 35384 | 16 | 41 | 0 | 0 | 1: 1442 | 0 / 0 |
| gemini OSD | 45600 | 44952 | 648 | 47 | 0 | 0 | 1: 3462, 2: 74, 3: 2 | 22 / 9 |
| gemini DV to HDR10 | 55800 | 55150 | 650 | 51 | 0 | 0 | 1: 3609, 2: 1 | 0 / 0 |

55,800 flips queued on amdgpu with `busy=0 timeouts=0`, no
"flip-pending", no failed commit, nothing from DRM or amdgpu in the kernel
log. Blocking commits rise by about three per title (start, refresh
change, stop), as on the N150. Queued to vertical blank: 41.6 ms at 24p,
16.5 ms at 60p (one refresh). Late flips appear only with Gemini Man's OSD
open (about 630 in that pass, warm-up included), where non-blocking still
raises presentation from 55.7 to 58.6 pictures/s.

## Functional checks (default settings)

`checks.py --only pause,seek,gui,verify --films 1917,gemini` and
`--only sequence` (raw files on Ollie, see below). Shortened by the
owner: no seek on Saving Private Ryan, no cadence, no verify-osd /
-subtitle / -transport / -hdr10, no checks with non-blocking on.

| check | result | evidence |
| --- | --- | --- |
| Dolby Vision signal | pass | Every Dolby Vision pass: Kodi committed `dv=1 rgb=1 max_bpc=8 hdr_blob=0` at 2160p23.976 or 2160p59.94; connector `DVBRIDGE_DV_STANDARD_LAB=1`, `DVBRIDGE_TUNNEL_FORMAT=0` (dolby-vision) in every window (`display.txt`); `=1` (hdr10) is not used, the HDR10 output mode is the engine's. Kernel (drm.debug=0x4, one 1917 start): "tunnel stream 3840x2160@24 vic 93 hdmi_vic 0, Dolby VSIF 81 01 1b 4b 46 d0 00 02 ..." (Dolby vendor InfoFrame, signal bit set). The box cannot see what the TV shows. |
| Verify output (`DVVK_VERIFY`) | pass | 1917 (FEL): 120 frames checked, 0 differed (7589 processed); Gemini Man: 120 checked, 0 differed (8039 processed). |
| Seeks, 1917 | pass | +30 s, -30 s, +10 min, -10 min, chapters, absolute, -10 s: 0 pool resets, no FEL message, every gap 1 afterwards. |
| Pause, GPU idle while paused | pass | 30 s paused: 0 flips, 0.0 % GPU render and decode busy, 4.4-4.6 W package. Matrix D (paused with the seek bar shown): 0.5-0.7 % GPU, 0.4-1.1 flips/s. The engine hands back its COMPUTE power profile when paused (level `auto`, profile `BOOTUP_DEFAULT`). |
| Resume | pass | first flip 103 ms (1917) / 55 ms (Gemini Man) after resume, every gap 1 afterwards, no holes. |
| Frame step | **fail** (as on the N150 at 24p) | 10 `FrameAdvance(1)` steps: the position moves one frame every time (41-42 ms at 24p, 16-17 ms at 60p), but steps 1, 2 and 6 flipped no new picture, on both films. On the N150 only 24p films did this; here Gemini Man (60p) does it too. |
| OSD and subtitle (GUI skipped while unchanged) | pass | 1917: 0 of 240 frames scanned the GUI in plain playback, 314 of 480 with the OSD open, 0 of 360 after it closed; Gemini Man 0 of 960, 48 of 1320, 0 of 1080. Engine GPU 14.3 ms plain, 17.9 ms OSD open (1917). |
| Return to the menu | pass | after every stop Kodi committed `dv=0 rgb=0 max_bpc=16` at 3840x2160@60 (the menu's mode); `DVBRIDGE_DV_STANDARD_LAB` 0 at the menu. |
| Titles in a row | pass | Airplane! (SDR, VAAPI H.264), 1917, Alien (HDR10), Gemini Man, Airplane!, 28 Years Later, Saving Private Ryan, 1917 opened over it: each at its rate (23.93-24.03 / 59.97 flips/s, every gap 1), the engine only for Dolby Vision titles, passthrough audio on all. |
| Audio passthrough | pass | TrueHD 8 ch bitstreamed (HDMI PCM S16_LE, 8 ch, 192 kHz) on 1917, SPR, Gemini Man; E-AC-3 on 28 Years Later (the TV's ELD lists no E-AC-3, Kodi still passed it through). |

## Logs

- Kodi, at every start: 15 error lines "Texture manager unable to load
  file: special://profile/addon_data/service.webostv/pointer/anim_*.apng"
  (Estuary YBLOD's LG/Denon/Sonos windows reference a pointer add-on that
  is not installed). No other error line in any pass or check.
- Kodi warnings in the measured passes and checks: "OutputPicture -
  timeout waiting for buffer" (32 in the default passes, 9 non-blocking,
  35 in the checks), "Pulseaudio module module-allow-passthrough not
  loaded" (once per passthrough device open), and once "Dolby Vision FEL:
  the enhancement layer lost its pairing (the stream ended before a common
  key frame)" when 1917 was opened over Saving Private Ryan in the title
  sequence.
- Kernel, the whole LibreELEC session: no DRM, amdgpu or DVBridge error.
  Boot only: "amdgpu: psp gfx command LOAD_TA(0x1) failed and response
  status is (0x7)" (Raven's TA load, at 0.55 s), "clocksource: Watchdog
  remote CPU 6 read timed out" (4.1 s). During the title sequence amdgpu
  printed "HDR SB:" lines (its HDR static metadata packet for Alien's
  HDR10).

## Box and boot

- `yblod-dv-prepare`: 28 s on the first boot of the profile (N150: 185 s);
  instant on the second (cache kept). Boot to SSH about a minute.
- While Dolby Vision plays, the engine selects the COMPUTE power profile
  (DPM level reads `manual`); stopped or paused: `auto`,
  `BOOTUP_DEFAULT`. The harness never wrote a clock or a level.
- Video decode (VCN 1.0) is the busier engine: 25-26 ms of decoder time per
  frame on the 24p films (about 62 % busy), 12.7 ms at 60p (about 76 %).
- Raw results on Ollie: `~/yblod-051/bench-amd/results/ryzen-y050`,
  `ryzen-y050-nb` (checks in `ryzen-y050/checks`).
