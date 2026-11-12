# Kodi playback benchmark

Made by `yblod/tools/bench/report.py`; the method and every definition are in `yblod/tools/bench/README.md`. A cell is the median of the repetitions, the lowest and highest repetition in brackets. `(!)`: a repetition failed one of its checks (listed at the end).

| image | version | kernel | CPU | GL | recorded (UTC) | display |
| --- | --- | --- | --- | --- | --- | --- |
| `y041` | yblod-0.4.1 | 7.3.0 | Intel(R) N150 | OpenGL ES 3.2 Mesa 26.2.5 | 2026-11-11T19:29:15+00:00 | unattended run: TV power state not observed; HDMI sink DENON-AVR (AVR in the chain) connected |

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

| film | scenario | y041 ms/frame | y041 ms/source frame | y041 fps | y041 drop/skip | y041 late |
| --- | --- | --- | --- | --- | --- | --- |
| 1917 | plain | 17.31 (17.30-17.32) | 17.30 (17.30-17.31) | 23.97 (23.97-23.97) | 0 / 0 | 0 |
| spr | plain | 23.09 (23.08-23.10) | 23.09 (23.08-23.09) | 23.97 (23.97-23.97) | 0 / 0 | 0 |
| 28yl | plain | 11.75 (11.75-11.76) | 11.75 (11.75-11.75) | 23.97 (23.96-23.97) | 0 / 0 | 0 |
| gemini | plain | 11.62 (11.62-11.63) | 7.86 (7.85-7.86) | 40.53 (40.49-40.57) | 0 / 8-15 | 1170-1174 |
| 1917 | OSD open | 31.39 (31.38-31.40) | 27.17 (26.96-27.39) | 20.75 (20.58-20.93) | 0 / 23 | 185-204 |
| spr | OSD open | 34.16 (34.12-34.21) | 27.29 (27.20-27.37) | 19.15 (19.07-19.24) | 0 / 16 | 286-295 |
| 28yl | OSD open | 18.36 (18.34-18.37) | 18.35 (18.34-18.37) | 23.97 (23.97-23.97) | 0 / 0 | 0 |
| gemini | OSD open | 21.15 (21.12-21.18) | 10.48 (10.47-10.48) | 29.70 (29.66-29.73) | 179-190 / 3-5 | 1792-1796 |
| 1917 | subtitle | 22.04 (22.04-22.05) | 22.04 (22.02-22.06) | 23.97 (23.96-23.98) | 0 / 0 | 0 |
| gemini | subtitle | 15.40 (15.40-15.41) | 8.35 (8.35-8.35) | 32.49 (32.48-32.51) | 104-108 / 13-14 | 1658-1659 |
| 1917 | DV to HDR10 | 19.11 (19.08-19.14) | 19.11 (19.09-19.14) | 23.98 (23.98-23.98) | 0 / 0 | 0 |
| gemini | DV to HDR10 | 14.89 (14.88-14.89) | 7.94 (7.91-7.97) | 31.96 (31.81-32.11) | 103-106 / 22-26 | 1672-1690 |

## Flip gaps

Gaps between flips in refresh periods, summed over the repetitions (`1: n` only is perfect), and the display's refresh rate.

| film | scenario | y041 gaps (Hz) |
| --- | --- | --- |
| 1917 | plain | 1: 2890 (23.974) |
| spr | plain | 1: 2894 (23.975) |
| 28yl | plain | 1: 2886 (23.975) |
| gemini | plain | 1: 2553, 2: 2342, 3: 2 (59.938) |
| 1917 | OSD open | 1: 2116, 2: 389 (23.975) |
| spr | OSD open | 1: 1730, 2: 581 (23.975) |
| 28yl | OSD open | 1: 2888 (23.975) |
| gemini | OSD open | 2: 3522, 3: 66 (59.938) |
| 1917 | subtitle | 1: 2894 (23.975) |
| gemini | subtitle | 1: 609, 2: 3317 (59.938) |
| 1917 | DV to HDR10 | 1: 2892 (23.975) |
| gemini | DV to HDR10 | 1: 498, 2: 3343, 3: 19 (59.938) |

## CPU, GPU clock and power

Kodi's render (main) thread and whole process in % of one core, the GPU's actual clock while awake (MHz, not pinned), package power (W, RAPL).

| film | scenario | y041 render thread % | y041 process % | y041 GPU MHz | y041 W |
| --- | --- | --- | --- | --- | --- |
| 1917 | plain | 6.0 | 29.4 (29.3-29.4) | 914 (904-925) | 5.0 (5.0-5.1) |
| spr | plain | 7.8 (7.7-7.8) | 28.8 (28.6-28.9) | 938 (936-940) | 5.8 (5.8-5.8) |
| 28yl | plain | 4.5 (4.4-4.5) | 16.2 (16.2-16.3) | 634 (633-634) | 3.5 (3.5-3.5) |
| gemini | plain | 9.2 | 36.2 (36.0-36.4) | 924 (923-925) | 5.4 (5.4-5.4) |
| 1917 | OSD open | 10.4 (10.3-10.5) | 35.1 (34.9-35.3) | 939 (938-940) | 6.0 (6.0-6.0) |
| spr | OSD open | 9.2 (9.2-9.3) | 30.8 (30.7-30.9) | 962 (952-971) | 6.1 (6.0-6.1) |
| 28yl | OSD open | 7.0 (6.9-7.0) | 19.6 (19.6-19.7) | 940 (940-941) | 4.5 (4.5-4.5) |
| gemini | OSD open | 9.3 | 34.7 (34.6-34.8) | 920 (919-922) | 5.7 (5.7-5.8) |
| 1917 | subtitle | 7.2 | 31.2 (30.9-31.6) | 924 (915-933) | 5.5 |
| gemini | subtitle | 8.1 | 35.2 (35.2-35.3) | 910 (907-914) | 5.4 (5.4-5.4) |
| 1917 | paused | 3.8 | 9.8 | 893 (888-898) | 4.6 |
| gemini | paused | 6.0 | 11.7 | 910 (891-929) | 5.4 (5.4-5.5) |
| 1917 | DV to HDR10 | 6.2 | 29.6 (29.4-29.8) | 926 (917-935) | 5.3 (5.3-5.3) |
| gemini | DV to HDR10 | 6.8 (6.7-6.9) | 31.1 (31.1-31.2) | 904 (893-914) | 5.4 (5.4-5.5) |

## Paused

60 s paused on a film frame: GPU render busy (% of wall time) and pictures flipped per second.

| film | y041 GPU busy % | y041 flips/s | y041 render thread % |
| --- | --- | --- | --- |
| 1917 | 46.8 (46.7-46.8) | 23.97 (23.97-23.97) | 3.8 |
| gemini | 75.0 (73.6-76.4) | 59.46 (59.41-59.51) | 6.0 |

## Playback start

Seconds from `Player.Open` to the first flip of uninterrupted presentation (median of the repetitions' medians; lowest and highest single start).

| film | y041 start s |
| --- | --- |
| 1917 | 1.43 (1.40-1.48, n=6) |
| spr | 1.63 (1.58-1.72, n=6) |
| 28yl | 1.20 (1.11-1.25, n=6) |
| gemini | 1.29 (1.26-1.34, n=6) |

## The two frame-time sources

Plain playback: DRM fdinfo (ms per presented picture, all of Kodi's render work) against the engine's own GPU timestamps (`DVVK_PROFILE`, mean of the 120-frame means; worst p95 and maximum), taken in a separate pass.

| image | film | fdinfo, log off | fdinfo, log on | engine mean | engine p95 / max | engine vs fdinfo (same pass) |
| --- | --- | --- | --- | --- | --- | --- |
| y041 | 1917 | 17.31 (17.30-17.32) | 17.54 (17.32-17.76) | 17.56 | 20.59 / 21.03 | +0.1 % |
| y041 | spr | 23.09 (23.08-23.10) | 23.09 (23.08-23.10) | 23.14 | 24.33 / 25.32 | +0.2 % |
| y041 | 28yl | 11.75 (11.75-11.76) | 12.18 (12.11-12.25) | 12.22 | 14.80 / 14.84 | +0.4 % |
| y041 | gemini | 11.62 (11.62-11.63) | 11.62 (11.62-11.62) | 11.58 | 11.96 / 12.20 | -0.4 % |

## Run-to-run spread

Half the range between the repetitions as a share of the median, for the frame time. A difference between two images smaller than this is noise. The last rows pool plain playback with the engine-log passes (scenario P), which measure the same thing when the log costs nothing.

| film | scenario | y041 repetitions (ms/frame) | y041 +/- % |
| --- | --- | --- | --- |
| 1917 | plain | 17.30, 17.32 | 0.0 |
| spr | plain | 23.10, 23.08 | 0.0 |
| 28yl | plain | 11.76, 11.75 | 0.0 |
| gemini | plain | 11.62, 11.63 | 0.1 |
| 1917 | OSD open | 31.38, 31.40 | 0.0 |
| spr | OSD open | 34.21, 34.12 | 0.1 |
| 28yl | OSD open | 18.37, 18.34 | 0.1 |
| gemini | OSD open | 21.12, 21.18 | 0.1 |
| 1917 | subtitle | 22.04, 22.05 | 0.0 |
| gemini | subtitle | 15.41, 15.40 | 0.1 |
| 1917 | DV to HDR10 | 19.08, 19.14 | 0.1 |
| gemini | DV to HDR10 | 14.88, 14.89 | 0.1 |
| 1917 | plain, with the engine-log passes | 17.30, 17.32, 17.76, 17.32 | 1.3 |
| spr | plain, with the engine-log passes | 23.10, 23.08, 23.10, 23.08 | 0.1 |
| 28yl | plain, with the engine-log passes | 11.76, 11.75, 12.25, 12.11 | 2.1 |
| gemini | plain, with the engine-log passes | 11.62, 11.63, 11.62, 11.62 | 0.1 |
