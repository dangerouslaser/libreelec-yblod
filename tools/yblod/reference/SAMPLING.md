# Isolating the final colour-enlargement step

This experiment asks whether the way we fill in colour between stored samples
can explain the remaining SK4 difference. It does not change the player, choose
a production filter, or treat hardware similarity as proof of correctness.

## Establish positions before comparing pictures

The prepared input declares left-sited 4:2:0 colour. Relative to the full-size
image, its samples sit at horizontal positions `2*i` and vertical positions
`2*j + 1/2`. To calculate image row `y`, the corresponding colour-plane position
is therefore `y/2 - 1/4`, not `y/2 - 1/2`.

This is consistent with the location diagram and enumeration in
[FFmpeg's pixel-format definitions](https://github.com/FFmpeg/FFmpeg/blob/n6.1.1/libavutil/pixfmt.h#L613-L635).
It validates the declared coordinate convention, not the SK4's internal filter
or our earlier choice to convert native top-left inputs to this convention.

`chroma_geometry_oracle.py` calculates tiny examples with exact fractions.
Its cubic interpolation uses endpoint values and slopes, a different numerical
route from the experimental filter's weighted kernel. Literal expected answers
cover constant colours, ramps and isolated bright rows/columns. Neither expected
answers nor filter coefficients are fitted to captured pixels.

The 26 new geometry tests pass on Ollie. They detect incorrect half-row shifts,
check global positions across strips, preserve the horizontal interpolation,
and exercise boundaries and cubic overshoot without silently clipping it.

## Change only one step

| Variant | Vertical interpolation | Declared position preserved? | Role |
| --- | --- | --- | --- |
| `linear-left` | Existing linear interpolation | Yes | Exact baseline |
| `cubic-left` | Cubic, fixed parameter -1/2 | Yes | Alternative filter experiment |
| `linear-top-control` | Linear, assumed centre at `2*j` | No | Deliberately wrong-position control |
| `linear-bottom-control` | Linear, assumed centre at `2*j+1` | No | Deliberately wrong-position control |

All variants retain horizontal linear interpolation, the same reconstructed
layers and instructions, colour conversion, range policy, final rounding and
transport packing. The two wrong-position controls are **not candidate fixes**,
even if a hardware score becomes smaller. They measure sensitivity to position.
The cubic choice is not asserted to be a prescribed Dolby filter.

This isolates the final source-colour enlargement after layer reconstruction.
It does not vary enhancement-layer scaling, earlier native-to-prepared colour
positioning, or whether reconstruction should happen before or after enlargement.
Intel Quick Sync and supported AMD media scaling remain requirements for the
eventual playback implementation; this CPU experiment does not replace them.

## Results across the four saved frames

All four linear baselines reproduced their saved transport frames byte-for-byte.
The table compares the existing linear filter with the correctly positioned
cubic alternative. Values are mean absolute differences from SK4 transport
codes, in I / P / T order; they are not visible-error ratings.

| Source frame | Existing linear | Correctly positioned cubic |
| --- | --- | --- |
| 461 | 4.8645 / 5.1382 / 5.5003 | 4.8670 / 5.1482 / 5.5085 |
| 1406 | 2.8688 / 4.8060 / 5.0347 | 2.8600 / 4.8068 / 5.0347 |
| 1960 | 13.2181 / 18.6671 / 9.3146 | 13.2188 / 18.6692 / 9.3178 |
| 2296 | 72.3907 / 157.3744 / 40.0069 | 72.3859 / 157.3851 / 40.0143 |

For frame 1960, the smooth-area differences also remain effectively unchanged:
`12.0501 / 13.5629 / 8.0254` with linear, versus
`12.0510 / 13.5651 / 8.0272` with cubic. This is not a case where a large edge
improvement hides an unchanged smooth-area error.

The alternating-row T error is not unique to frame 1960. The baseline difference
between even- and odd-row signed means is approximately `8.6365`, `8.8874`,
`8.8171`, and `7.4684` codes in these four frames. Neither cubic interpolation
nor the deliberately incorrect half-pixel position controls removes it. In
frame 1960, all tested variants leave that gap between `8.8163` and `8.8184`.

Some wrong-position controls produce smaller numbers for individual channels.
They still fail the declared geometry and do not resolve the row pattern.
Choosing them because of those smaller numbers would be precisely the kind of
unexplained hardware fitting this investigation is intended to avoid.

Frame 2296 retains the previously observed large direct-policy discrepancy.
The earlier colour-limit experiments addressed a different variable; this run
intentionally holds that policy fixed. The result does not reverse or settle
the separate investigation into extreme-value handling.

**Conclusion:** these final vertical interpolation alternatives do not explain
the main discrepancy. The experiment does not eliminate every possible
resampling algorithm, nor validate earlier preparation/reconstruction stages.
There is no basis here for changing the production filter.

The next investigation should verify capture/packing precision and the common
alternating-row pattern, then isolate earlier colour preparation and the order
of reconstruction versus enlargement. Those are separate hypotheses; none is
established as the cause by this result.

Start the capture check with the existing files: split the transported upper
eight and lower four bits, retain their original rows, and determine which part
carries the alternating difference. The saved RGB8 buffer format is not itself
evidence of eight-bit Dolby precision: CoreELEC documents
[12-bit IPT carried in RGB8](https://github.com/CoreELEC/common_drivers/blob/4dbe1c27ae176fde4c1cbef7506618fd7f62b976/drivers/media/enhancement/amdolby_vision/amdv_hw.c#L3237).
Metadata checksums do not independently establish untouched image-code bits.
The row pattern is not proof of dithering, and broad hardware bypass flags
should not be changed merely to see whether the score improves.

## Comparison safeguards

The comparison must reproduce every byte of the saved baseline transport frame,
including borders, before it can report success. Source planes, reconstructed
output, metadata, capture and baseline reports carry checked hashes. All three
copies of both captured metadata packets must agree and pass their checksums.

Scores retain the original picture coordinates. Each channel uses the same
capture-derived smooth/edge masks across all four variants. Alternating rows
are reported separately using their original frame row numbers. No shift,
offset, gain or filter parameter is fitted to the capture. Changes relative to
the baseline are reported separately from differences relative to the SK4.

The visible-counter association of the saved captures remains an input to the
experiment, not an independently established result. Pixel-code differences
are not perceptual scores or a Dolby conformance test.

## Resource policy

The experiment operates on 32-row strips and writes numerical reports only,
not new movie images or full-size floating-point intermediate stages. Heavy
jobs run one at a time on Ollie under `MemoryMax=512M`, `MemorySwapMax=0`, with
one numerical-library thread. The external memory cap is mandatory for this
workflow; the Python tool does not impose it itself.

The four final comparison jobs completed in approximately 8.6–9.6 seconds each,
with peak process RSS no greater than **96,216 KiB**, no swaps and no OOM failure.
These timings describe offline diagnostics, not real-time playback performance.

## Reports and reproduction

The numerical reports contain the experiment and filter source, dependency
hashes, numerical-library version, input identities and all per-channel groups:
[461](results/sampling-461.json), [1406](results/sampling-1406.json),
[1960](results/sampling-1960.json), [2296](results/sampling-2296.json).
The [four-frame summary](results/sampling-summary.json) retains individual frames
and labels the wrong-position controls; it does not pool scores or choose a winner.

With the matching existing local bundles and SK4 capture, run from the repository
root, selecting a report filename that does not already exist:

```sh
systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0 -- \
  env OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 tools/yblod/reference/sampling_experiment.py \
  target/sk4-sweep-1960-direct \
  target/reference-frame-1960-composed-linear \
  target/reference-frame-1960-streamed "$SK4_CAPTURE" \
  --report target/sampling-1960-reproduced.json
```

Set `SK4_CAPTURE` to the corresponding saved `native.rgb`. Raw movie/capture
pixels are not published. The synthetic tests require no movie or capture:

```sh
python3 -m unittest discover -s tools/yblod/reference -p 'test_chroma_geometry*.py'
python3 -m unittest discover -s tools/yblod/reference -p 'test_sampling_experiment.py'
```
