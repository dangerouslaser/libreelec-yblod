# Raw Y416 isolated steps and stripe impulses

2026-10-05; same V11 binary, Intel8086:9a49/i915, iHD26.3.5(3de4708) and
LibreELEC VM as the constant/gradient diagnostics. No playback settings changed.
Full provenance and raw centre-line profiles: `results/intel-y416-edges-v11.json`.

All78 sequential jobs completed:26 exact P010 copy/native gates, then52 Y416
observations (13cases ×native64/enlarged128 ×two repeats). Every repeat matched.
Each case changed only Y, Cb or Cr on one axis, with a512→576 step or one-native-
sample-wide576 stripe on a512 background. Change index32 in64-sample Y,16 in
32-sample chroma. These are stripe impulses, not2D point impulses.

Requests retained DEFAULT, BT2020/REDUCED, LEFT6→unspecified0, pipeline0 and exact
Y416/YUV444_12. The output surface was explicitly unadvertised allocation
diagnostic; there was no fallback. All raw16-bit words were preserved.

## Whole-frame observations

- No non-driven colour or alpha words changed versus the same-size neutral
  baseline, across any case. This is a measured whole-frame comparison.
- Alpha remained65535 at64 and65280 at128; it is not a colour error or corrected
  by these tools. The tracked source colour sampler ignores it.
- Native Y steps/stripes were exact; native chroma stripes duplicated each source
  sample twice. This is a measured response, not unique proof of a filter.
- At128, step plateaus reached the known512 and576 values. Between them the
  response overshot/undershot, with different horizontal and vertical chroma
  responses. Cb and Cr profile responses matched each other.

Measured128 centre-line responses in native-code units (rawword/64), relative
to the separately captured512 baseline. Stimulus amplitude is64, not fitted:

| Driven component/axis | Step response min/max | Stripe response min/max |
|---|---|---|
| Y horizontal/vertical | −10/74 | −13/64 |
| Cb/Cr horizontal | −5/69 | −5/64 |
| Cb/Cr vertical | −4/68 | −4/72 |

These mild-stimulus overshoots remain within the representable colour range.
They are not evidence for adding a nominal-range clamp, nor proof of the
licensed Dolby player's filter. Response statistics, not movie matching, are
the purpose of this test. Profile measurements must not be interpreted as
calibration corrections or independently certified physical registration.

## Engine and resource observations

Of26 native Y416 submissions,3 recorded positive video-enhance intervals and23
no positive engine interval. Of26 enlarged submissions,16 recorded positive
render intervals and10 no positive interval. No other positive classes were
observed. These tiny intervals neither establish a dedicated SFC route nor
justify extrapolation to full-size playback.

Python peakRSS29412KiB; elapsed2.35s under512MiB/no-job-swap constraints. These
are synthetic test costs, not a playback benchmark. Next hardware checkpoint
must test full-size Y416, where allocation and routing may differ substantially.

The independent saved-profile scorer publishes exact fixed-stimulus plateau
errors,10/50/90% crossing brackets and widths, stripe signed/absolute masses,
positive/negative lobes, support and descriptive centroids in
`results/intel-y416-edge-metrics-v11.json`. It performs no gain/area normalization,
fitted phase correction or image-hash revalidation. All fixed plateau check bands
had zero error. Centroids from one central stripe do not establish a universal
filter phase, and the metrics must not be used as calibration corrections.

Ollie passes467 reference tests (including16 new metric tests) plus8 accuracy
tests under bounded scopes. Synthetic job timings are not these test timings or
steady-state playback measurements.

Reproduction:

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 hardware_y416_edges.py ./vaapi_scaler_probe-v11 NEW-DIRECTORY --repeats 2

python3 y416_edge_metrics.py NEW-DIRECTORY/y416-edges-report.json NEW-METRICS.json
```
