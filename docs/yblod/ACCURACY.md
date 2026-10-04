# Dolby Vision accuracy against Dolby hardware

yblod's Dolby Vision output was measured against licensed Dolby Vision hardware players and tuned to
match them. This page explains how it was measured, what changed and where it landed.

## Reference devices

| Device | Chip | Software | Mode |
|---|---|---|---|
| Ugoos AM9 Pro | Amlogic S928X | CoreELEC 22 | TV-led (Standard) Dolby Vision |
| Ugoos SK4 | Amlogic S7D | CoreELEC 22 | TV-led (Standard) Dolby Vision |

Both run Amlogic's licensed Dolby Vision hardware. The SK4 is a different chip generation with a different
Dolby driver build, which makes it a useful second opinion.

## How it was measured

1. **Capturing the reference.** CoreELEC boxes can loop their HDMI encoder output back into memory (VDIN1
   loopback of `venc0`). The frame is stored with every 64-bit word byte-reversed; once reversed, each pixel
   is exactly the HDMI Dolby Vision tunnel (12-bit 4:2:2 in 8-bit RGB). The Dolby metadata hidden in the
   chroma bits decodes with a valid CRC, which proves the capture is the exact signal the TV receives.
   (`tools/yblod/accuracy/cecapture.sh`)
2. **Capturing yblod.** A private test build reads back the packed HDMI frame Kodi sends. It is not part of
   any release.
3. **Matching frames.** Every frame of the test clip is rendered offline, and each reference capture is
   matched to the frame with the closest picture. Only unambiguous matches are used.
4. **Comparing.** The two devices send different but equally valid signals (see below), so both are
   converted through the matrices in their own Dolby metadata into Dolby's LMS colour space, and compared in
   12-bit PQ code values. About one code is roughly the smallest difference the eye can see.
5. **Fitting.** An offline renderer (`tools/yblod/accuracy/dvfit.c`) uses the same libplacebo and FFmpeg as
   Kodi and renders exact frames with candidate settings, so each change could be scored against the
   reference before it went into the engine.

## What changed

| Change | Why |
|---|---|
| **Tunnel sent as IPT-PQ-c2** | Dolby hardware converts the picture to IPT before sending it and signals IPT matrices in its metadata; the engine sent BT.2020 YCbCr. Both are valid, but subsampling chroma in a different colour space gives different results at colour edges. yblod now encodes exactly like the hardware and signals the same matrices. |
| **Hardware-matching offset** (setting, on by default) | Both reference devices sit a constant few codes away from the exact conversion (in IPT codes: I −5.07, P −7.94, T +3.62). The offset was the same on both chips and steady from frame to frame. Player > Videos > Dolby Vision > "Match Dolby hardware levels" turns it off. |
| **Chroma siting fix** | The engine never told libplacebo that HEVC / Dolby Vision chroma is left-sited, so colour was placed a quarter of a chroma pixel off. This was a pre-existing bug, found because the error lined up exactly with horizontal colour slopes. |
| **Co-sited 4:2:2 packing** | Chroma for each pixel pair is taken from the even pixel instead of averaging the pair, which is much closer to the hardware. |
| **Gaussian chroma upsampling** | Of libplacebo's filters, Gaussian was closest to the hardware on every matched frame (Lanczos, the previous default, was the furthest). |

The enhancement-layer upscaling filter made no measurable difference (all candidates within 0.05 codes),
so scaling the enhancement layer on the Intel media engine (Quick Sync) costs nothing in accuracy.

## Results

Real HDMI frames from yblod, compared with the reference devices on the same frames, as sent (nothing
removed). Profile 8.1 test clip. Units: 12-bit PQ codes in Dolby LMS.

**Against the AM9 Pro** (4 matched frames)

| | Original engine | yblod |
|---|---|---|
| Typical pixel (median) | 4.37 | **0.72** |
| RMS | 6.27 | **1.48** |
| Pixels within 1 / 2 / 4 codes | 1.0% / 5.3% / 42.5% | **62.6% / 86.8% / 97.9%** |
| Worst 1% of pixels | 14.4 | **4.8** |
| Colour edges (RMS) | 16.4 | **3.4** |
| Overall offset (L / M / S) | −4.5 / −3.1 / −7.8 | **+0.2 / +0.1 / −0.2** |

**Against the SK4** (2 matched frames)

| | Original engine | yblod |
|---|---|---|
| Typical pixel (median) | 4.48 | **1.74** |
| Pixels within 4 codes | 43.2% | **82.3%** |
| Colour edges (RMS) | 16.6 | **4.8** |

The typical pixel now matches the AM9 Pro to within a single code, below what is visible, and colour edges
are about five times closer than with the original engine. The SK4 agrees on every improvement; its remaining
spread is a little larger, partly because it is a different Dolby chip generation and fewer frames matched.

## Limits

- The headline numbers come from one Profile 8.1 clip. Profile 7 FEL content showed a larger remaining
  difference in offline tests (about 6.5 codes RMS) from something in FEL composition; it does not depend on
  the scaling filter and is being investigated.
- Both references are Amlogic devices. The constant offset was identical on two chip generations, which is
  why it is on by default, but it is a setting because no non-Amlogic Dolby device has been measured yet.
- The reference captures include whatever the hardware does; the aim is to match a licensed player's output,
  not a mathematical ideal.

## Tools

`tools/yblod/accuracy/` holds everything used here: the tunnel decoder for both capture formats, the
LMS conversion, the CoreELEC capture script, frame matching, scoring, and the offline renderer.
