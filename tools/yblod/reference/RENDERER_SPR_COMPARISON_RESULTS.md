# Saving Private Ryan earlier renderer comparison

The current native engine uses substantially more GPU rendering capacity than
the retained earlier renderer on the same Saving Private Ryan scene. Both paths
played steadily during the measured windows. Their pixels differ, so the earlier
renderer is not an output-preserving replacement for the current engine.

## Matched playback results

On 2026-10-06, the same installed binary played the scene starting at 20 minutes
for 180 seconds per case, in earlier/current/current/earlier order. Kodi restarted
and settled for at least 20 seconds before each case. Both conditions retained
the same output settings and enhancement-layer-only media scaling selection.

| Balanced measurement | Earlier renderer | Current native engine |
| --- | ---: | ---: |
| GPU render client busy percent | 10.7550 | 59.3680 |
| GPU video decode client busy percent | 6.2743 | 5.3496 |
| GPU video enhancement client busy percent | 11.1968 | 9.4731 |
| GPU copy client busy percent | 0 | 0 |
| Whole Kodi CPU percent of one core | 14.1079 | 19.3038 |
| Steady playback drops and skips across both runs | 0 and 0 | 0 and 0 |

GPU measurements are elapsed-time-weighted, deduplicated Kodi DRM client
counters, not exclusive shader timings. CPU includes all Kodi threads; 100 percent
means one occupied core. Utilization percentages from different GPU engines must
not be added or treated as interchangeable capacity.

All four runs had normal playback speed, no steady stalls, zero dropped frames,
and clean player-stop and service shutdown. The repeated current-engine case
recorded one startup/seek skip, with no additional skips in its steady window.
The other three cases recorded no skips. The controller exited successfully and
restored the prior service override without automatically restarting Kodi.

The control is the earlier renderer retained in this binary, not a pristine
upstream CroqueMr release or the exact historic low-utilization build. Actual
routes differ: earlier steady playback uses direct LMS conversion and packed
output; the native engine uses release RGB colour conversion and separate
packing. The media scalers also use different output formats. This comparison
therefore measures whole rendering paths, not the isolated cost of one feature.

## Output preservation and optimization target

Three matched source frames were captured privately from both paths at identical
base-layer and enhancement-layer timestamps with identical source metadata.
The first comparison has nonzero I, P, and T code differences; playback health
alone cannot establish which path is more accurate or Dolby conformant.

The optimization target is the current engine's output. The first candidate
combines its final colour stage with transport packing while retaining native
reconstruction, chroma expansion, release RGB colour math, and black-border
offset handling. It remains disabled by default pending runtime qualification.

All three repeated current-engine frames preserve the full-raster picture and
metadata payload exactly. They differ in 48, 132, and 132 transmitted RGB bytes,
confined to validated metadata update IDs and their CRCs. The serializer increments
its four-bit ID on metadata payload changes, so different startup histories can
produce different transport bytes at the same source timestamp. All packet
repetitions and CRCs pass; no scene-refresh or other payload difference is allowed.
The I, P, and T planes below the four metadata rows have zero maximum difference
and 100 percent exact values in all three repeats.

The comparison tool offers two distinct gates. `--require-exact` requires identical
transmitted RGB bytes and fails these repeats. The separate semantic validation
`--require-picture-and-payload-preserved` permits only the independently validated
update-ID and CRC bit changes; it requires exact pixels everywhere else, including
borders and the remaining metadata-row bits. It does not relax pixel tolerances.

Capture readback runs are separate from utilization measurements. Raw film frames
and source metadata remain private. The sanitized
[performance measurements](RENDERER_SPR_COMPARISON_RESULTS.json) contain the four
route, health, lifecycle, CPU, and GPU records.
