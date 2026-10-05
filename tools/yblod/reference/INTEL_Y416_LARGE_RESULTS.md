# Full-size raw Y416 safety and isolated affine bands

2026-10-05; Intel8086:9a49/i915, iHD26.3.5(3de4708), libva2.24.0/API1.24,
same LibreELEC VM and V11 standalone binary as earlier Y416 diagnostics.
P0101920x1080 input, nativeY4161920x1080 and enlargedY4163840x2160.
No playback, output mode or display settings changed. Kodi remained active.

## Safety gate and completed corpus

The separate six-job neutral safety checkpoint completed first: exact copy/native
P010 gates, then two repeated native and two repeated enlarged Y416 jobs. Colour
words remained32768 throughout. Native alpha was65535, enlarged alpha65472.
Scope memory peak340250624bytes (~324.49MiB), memory.events max/oom/oom_kill0,
swap0. Aggregate: `results/intel-y416-large-neutral-v11.json`.

Only then did the seven-case42-job run start:14 exact P010 gates before28 Y416
submissions, including two repeats per native/enlarged case. All completed and
all repeats matched. Corpus: neutral plus isolated Y/Cb/Cr x/y ascending ramps
in96-native-sample bands, centred at512, bounded plateaus128/888 outside the
band. Source slopes are+8 codes/sample; no descending, edge, clipping or
multi-phase impulse acceptance is established by this checkpoint.

Exact requests remain DEFAULT, BT2020/REDUCED both sides, LEFT6→unspecified0,
pipeline flags0 and explicit Y416/YUV444_12. Output surface advertisement was
false in every conversion, so these remain labelled allocation/submission
diagnostics, not a portable advertised backend contract or Dolby certification.
No substitute format or fallback was used.

## Whole-frame and centre-line observations

Every non-driven colour component and alpha matched the same-size neutral
baseline by its whole-frame raw-word hash. Cb/Cr active responses matched each
other by their raw-word hashes. Native Y transport was exact; native chroma
centre lines repeated source samples in pairs, yielding diagnostic affine
errors−4/0 horizontally and±2 vertically against the declared LEFT-grid ideal.
That response does not uniquely identify a filter.

The enlarged raw colours contained low6-bit offsets0/16/32/48, observing
quarter-code values. All colour low4 bits were zero in this corpus. This is not
proof of a universal effective12-bit limit or permission to drop remaining bits.
Alpha was65472 for every enlarged case, different from tiny128-output alpha65280;
the tracked source colour sampler ignores it. The loaded Kodi binary has not
been proven identical to the inspected source.

`y416_large_geometry.py` independently scores centre-line band interiors against
the same three predeclared physical-coordinate hypotheses as the small probes.
It preserves raw/64 fractions, uses32-output-sample margins and chroma's4x native
grid expansion at2x image enlargement. Centre-line comparisons are not
whole-frame colour/geometry acceptance; no image hashes are re-read by the scorer.

Enlarged affine-band error sets in native-code units:

| Driven component/axis | Co-sited hypothesis | Pixel-centre hypothesis | Mixed Annex-B example hypothesis |
|---|---|---|---|
| Y horizontal | −5/2,−3/2 | −1/2,+1/2 | −5/2,−3/2 |
| Y vertical | −5/2,−3/2 | −1/2,+1/2 | −1/2,+1/2 |
| Cb/Cr horizontal | −5/4,−3/4 | −1/4,+1/4 | −5/4,−3/4 |
| Cb/Cr vertical | −5/4,−3/4 | −1/4,+1/4 | −1/4,+1/4 |

These errors are relative to explicitly declared ideal sampling models, **not**
licensed-player ground truth. Smaller errors against one model are not evidence
of improved SK4 matching or a uniquely recovered phase/kernel. No adjustment was
fitted or applied, and the production renderer's later horizontal sampling is
outside this raw-surface measurement.

Aggregates: `results/intel-y416-large-v11.json` and
`results/intel-y416-large-geometry-v11.json`. They pin source/helper/binary and
input/output hashes, exact commands, API-log hashes, profiles, and scoring source.

## Engine and memory measurements

All14 native and14 enlarged Y416 jobs recorded positive video-enhance intervals;
render/copy/video intervals were zero. All seven submitted P010 native gates
also recorded positive video-enhance intervals. This is DRM engine-class
accounting, not proof of SFC specifically or a steady-state playback benchmark.
Tiny64→128 Y416 results selected a measurably different engine class, so neither
their coordinates nor their costs should substitute for these full-size results.

The42-job scope reached its512MiB cap and recorded1260 `max` events, with
`oom`, `oom_kill` and `oom_group_kill` all0 and current swap0. The cap was not
raised. Cgroup peaks include more than Python RSS; these counters do not bound
every driver/GPU allocation. Python peakRSS38316KiB; `/usr/bin/time -v` reported
maximumRSS151464KiB for the measured command, elapsed36.24s, swaps0, exit0.
Runner elapsed34.74s includes CPU scanning and I/O and is **not playback cost**.

Afterwards Kodi was active, VM available memory about2.16GiB and `/storage`
had7.5GiB free. Raw synthetic files/logs were preserved privately; no films or
device captures were published. Ollie passes480 reference plus8 accuracy tests
under512MiB/no-job-swap scopes.

## Reproduction and remaining work

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 hardware_y416_large.py ./vaapi_scaler_probe-v11 NEW-NEUTRAL --neutral-only
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 hardware_y416_large.py ./vaapi_scaler_probe-v11 NEW-LARGE
python3 y416_large_geometry.py NEW-LARGE/y416-large-report.json NEW-GEOMETRY.json
```

Next: opposite slopes, steps and multiple impulse phases at full size, followed
by bounded composition/NLQ fixtures. Offload availability, spatial accuracy,
metadata interpretation and playback benefit remain separate acceptance gates.
