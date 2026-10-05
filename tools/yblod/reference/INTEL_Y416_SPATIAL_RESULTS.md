# Raw Y416 isolated-gradient observations

2026-10-05; same Intel8086:9a49/i915, iHD26.3.5(3de4708), LibreELEC VM
as the constant diagnostic. Standalone V11 binary retained; no playback changes.
Full provenance is in `results/intel-y416-spatial-v11.json`.

All78 jobs completed:26 exact P010 copy/submitted native gates, followed by52
Y416 jobs (13cases ×native64/enlarged128 ×two repeats). All repeated raw hashes
matched. Each test changed only one component along one axis, slope+8 or−8
native codes/sample, centred at512. Other colour components remained exactly512
over the whole output. Alpha was65535 at64 and65280 at128, independently of
the gradient. Alpha is ignored by the production colour sampler; this difference
is still preserved in the report, not hidden or treated as a colour error.

All Y416 output allocations were unadvertised, explicitly labelled diagnostics;
successful execution does not qualify a portable backend. Requests were DEFAULT,
BT2020/REDUCED both sides, input LEFT6/output unspecified0, pipeline flags0.

## Precision and coordinates

Native colour words had zero low6 bits. Enlarged colour words included offsets
16/32/48 in the low6 bits: fractional quarter-code precision was observed in
this corpus. All colour words had zero low4 bits. This does not prove the general
effective precision or identify the interpolation filter.

Exact coordinate hypotheses, not fitted predictions:

| Image-coordinate mapping at2x | Source Y coordinate | Source LEFT420 chroma coordinate |
|---|---|---|
| Co-sited | `(x/2,y/2)` | `(x/4,y/4−1/4)` |
| Pixel-centre | `(x/2−1/4,y/2−1/4)` | `(x/4−1/8,y/4−3/8)` |
| Informative Annex-B mixed example | `(x/2,y/2−1/4)` | `(x/4,y/4−3/8)` |

The centre-line comparisons retain raw words/64 as exact rational native codes,
excluding16 output samples at each edge. Representative2x error sets against
the **co-sited hypothesis**, not a mandatory Dolby reference:

| Component/axis | Ascending errors | Descending errors |
|---|---|---|
| Y horizontal or vertical | 0,+1/4 | 0 |
| Cb/Cr horizontal | −1/4,0,+1/4 | −1/4,0,+1/4 |
| Cb/Cr vertical | −2,0,+2 | −2,0,+2 |

Atnative1x, Y matched all hypotheses exactly; chroma comparisons showed
alternating errors (horizontal ascending−4/0, descending0/+4; vertical±2).
This is consistent with repeated chroma samples in these tiny native profiles,
but does not uniquely identify the driver's filter. No constant phase/gain
correction was inferred or added. All three hypotheses and modulo4 errors are
published in `results/intel-y416-geometry-v11.json`.

The production renderer's later horizontal sampling adjustment is outside these
raw-surface measurements. A conditional source-coordinate explanation is not
proof of the selected runtime filter, and that adjustment must not be added again.

## Engine and test costs

Of26 native Y416 submissions,1 had a positive video-enhance interval;25 had
no positive measured engine-class interval. Of26 enlarged submissions,23 had
positive render intervals and3 no positive intervals. No other positive classes
were observed. Zero intervals do not prove no GPU activity; these tiny timings
do not identify SFC or establish full-size routing. Prior full-size P010 default
tests used video-enhance; **do not extrapolate either format/size to the other**.

Python peakRSS29684KiB, elapsed1.71s; scope512MiB/no-job-swap. These are synthetic
test costs, not playback performance. Ollie passes442 reference tests and the
previously verified8 accuracy tests. Kodi remained active.

Next: isolated steps/stripes, then full-size rawY416 measurements. No SK4-match
improvement, output correction or production acceptance is claimed.
