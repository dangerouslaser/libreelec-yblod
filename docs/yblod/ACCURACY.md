# Hardware comparisons, historical fitting, and correctness tests

yblod's existing playback output was measured against hardware players and tuned
to reduce those differences. That historical work is documented below, including
the fitted offset; it is not being relabelled as an independently proven Dolby
implementation. The project is not Dolby-certified.

## Current acceptance criteria

The objective is to justify processing behaviour, not reproduce one device at
any cost. A hardware match is supporting evidence, not proof of correctness.

1. Check individual operations against independently calculated answers from
   documented rules. Label experimental choices separately from specified rules.
2. Preserve exact source frame/layer/metadata association and inspect intermediate
   values before changing final output. A mismatch can originate earlier in the chain.
3. Change one assumption at a time and test both the affected region and ordinary
   regions. Report regressions, not only the average improvement.
4. Check additional content and colour instructions not used to choose the rule.
   No fitted output offsets are allowed in the standalone correctness reference.
5. Keep hardware agreement, arithmetic correctness, playback performance and
   certification as separate claims. None implies the others.

The [standalone reference](../../tools/yblod/reference/README.md) implements this
experimental workflow separately from playback. Its public reports currently
cover four numbered Profile 7 frames and five colour-limit controls. They expose
small regressions as well as improvements. They do not settle the correct place
to limit values, eliminate other reconstruction errors, or establish general
movie accuracy. SK4 Pro is the current comparison device; no new AM9 capture is
required for this phase. Independent synthetic tests are needed because all four
numbered frames use the same source colour matrices and offsets.

The implementation uses public specifications and attributed open-source code
where applicable. It is not presented as a formal clean-room implementation.
Source provenance and dependency licenses must remain documented; publication
does not itself provide patent clearance or Dolby certification.

## Historical comparison devices

| Device | Chip | Software | Mode |
|---|---|---|---|
| Ugoos AM9 Pro | Amlogic S928X | CoreELEC 22 | TV-led (Standard) Dolby Vision |
| Ugoos SK4 | Amlogic S7D | CoreELEC 22 | TV-led (Standard) Dolby Vision |

Both are Amlogic-based Dolby Vision players, with different chip generations and
driver builds. Agreement between them is useful evidence, but they are not two
fully independent implementations of the standard. Their licensing status does
not transfer to this project or make every captured behaviour mandatory.

## How the historical comparison was measured

1. **Capturing the reference.** CoreELEC boxes can loop their HDMI encoder output back into memory (VDIN1
   loopback of `venc0`). The frame is stored with every 64-bit word byte-reversed;
   the decoded layout is consistent with the Dolby Vision tunnel (12-bit 4:2:2
   carried in 8-bit RGB). Valid metadata CRCs support the byte layout and metadata
   recovery. They do **not** by themselves prove pixel accuracy, correct frame
   alignment, electrical HDMI equivalence, or the picture a TV finally displays.
   (`tools/yblod/accuracy/cecapture.sh`)
2. **Capturing yblod.** A private test build reads back the packed HDMI frame Kodi sends. It is not part of
   any release.
3. **Matching frames.** Every frame of the test clip is rendered offline, and each reference capture is
   matched to the frame with the closest picture. Only unambiguous matches are used.
4. **Comparing.** The implementations use different colour representations (see below), so both are
   converted through the matrices in their own Dolby metadata into Dolby's LMS colour space, and compared in
   12-bit PQ code values. A code difference is a signal metric, not a universal
   threshold of human visibility; no controlled viewing study is claimed here.
5. **Fitting.** An offline renderer (`tools/yblod/accuracy/dvfit.c`) uses the same libplacebo and FFmpeg as
   Kodi and renders exact frames with candidate settings, so each change could be scored against the
   reference before it went into the engine.

## Historical playback changes and their evidence

| Change | Why |
|---|---|
| **Tunnel sent as IPT-PQ-c2** | The captures signalled IPT matrices; the original engine used BT.2020 YCbCr. Chroma subsampling in different representations can change edge samples. Signalling the observed matrices reduced sampled differences; it does not establish that every internal processing step matches the hardware. |
| **Hardware-matching offset** (setting, on by default in playback) | Fitted IPT offsets are I −5.07, P −7.94, T +3.62. They reduced error on the sampled material, but their physical/algorithmic cause has not been established. They are not specified Dolby corrections and may conceal an earlier discrepancy. Switching "Match Dolby hardware levels" **off** disables them; the standalone reference never applies them. |
| **Chroma positioning change** | Explicit chroma-position handling reduced edge-correlated errors. Do not generalize this to all HEVC/Dolby content being left-sited: our numbered test declares top-left chroma. The standalone reference records the native position and its experimental conversion explicitly. |
| **Co-sited 4:2:2 packing** | Taking chroma from the even pixel rather than averaging each pair reduced differences on the tested captures. Further validation is needed before treating this as a universal requirement. |
| **Gaussian chroma upsampling** | Gaussian was selected because it scored best among tested libplacebo filters on the matched sample. That is an empirical fit, not evidence of the proprietary scaler's exact filter or general correctness. |

The tested enhancement-layer filter candidates were within 0.05 codes in that
measurement. This does not establish that all filters, content, bit depths or
hardware backends are interchangeable. Quick Sync offload remains a production
requirement; it needs separate precision, format, phase and performance checks.
An equivalent supported AMD media-engine path is also a production requirement,
but is not yet implemented or validated by this reference work.

## Historical sample results (not new standalone-reference results)

Captured output from yblod compared with the device captures on matched frames,
including the playback engine's fitted offset. Profile 8.1 test clip.
Units: 12-bit PQ codes in the common LMS comparison representation. These figures
are historical measurements, not a fresh rerun or certification test.

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

The measured median difference against AM9 Pro was below one code on these four
frames. This is not a claim that the output is perceptually indistinguishable or
correct for other material. The two SK4 samples had larger differences; their
cause is not established simply by noting the different chip generation.

## Limits

- The historical headline numbers come from one Profile 8.1 clip, with too few
  frames to establish general accuracy. Earlier Profile 7 tests showed larger
  discrepancies (about 6.5 codes RMS in that comparison); this does not localize
  the error to a particular step or rule out scaling/phase interactions.
- Both historical reference devices are Amlogic-based. The fitted offset was
  reported as consistent across the sampled captures from two generations;
  that does not establish a universal correction. Neither its cause nor broader
  applicability has been demonstrated, and no non-Amlogic player was measured.
- Captures include the device's choices, rounding and potential quirks. A lower
  difference can reflect a better implementation or imitation of those choices;
  independent evidence is needed to distinguish them.
- The new reference's numerical I/P/T transport scores and the historical
  colour-converted LMS scores are different metrics. Do not compare their
  numerical values as if they were the same accuracy measure.

## Tools

`tools/yblod/accuracy/` holds everything used here: the tunnel decoder for both capture formats, the
LMS conversion, the CoreELEC capture script, frame matching, scoring, and the offline renderer.
