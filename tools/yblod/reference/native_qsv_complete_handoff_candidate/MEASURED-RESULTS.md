# Complete handoff: measured results, 2026-10-06

The candidate successfully delivered both QSV-decoded layers to native
reconstruction. One exact matched frame's canonical whole RGB picture, Dolby
payload, source metadata and BL/EL timestamps matched the retained qualified
reference. This is not whole-film or display-conformance evidence.

Four 90-second Saving Private Ryan windows beginning at 20 minutes were run in
0/1/1/0 order. Only BL decoding changed: VA-API versus QSV. EL QSV, scaling,
FP32 native reconstruction, planar/direct-packed output and the FFmpeg/VPL
libraries stayed fixed. Capture, batched planes and immutable instructions
were disabled during measurement. All four runtime, reconstruction, player-stop
and clean-shutdown checks passed. The working binary, settings, library maps
and idle state were restored. No controller OOM or swap was observed.

| Metric, paired-run mean | BL VA-API + EL QSV | Both QSV |
| --- | ---: | ---: |
| Whole Kodi CPU, % of one core | 16.56 | 17.10 |
| GPU render engine, capacity-normalized % | 30.06 | 29.68 |
| GPU decode engines, capacity-normalized % | 5.36 | 4.46 |
| GPU video-enhance engine, % | 9.52 | 9.46 |
| Copy-engine activity, % | 0 | 0 |
| Mean of each run's maximum sampled Kodi memory, GiB | 1.697 | 1.431 |
| Reported drops in both runs | 0 | 0 |
| Reported skips in initial seek/transition interval, per run | 0 | 1 |
| Reported steady-state drops/skips/stalls | 0/0/none | 0/0/none |

GPU values come from actual process-client counter intervals, each covering
about 88.6 seconds. Memory is maximum sampled service MemoryCurrent, not an
allocator-only measurement or proof of a lower true peak. The initial QSV skip
is explicitly retained; it must not be described as zero skips throughout.

Interpretation: the complete metadata handoff fixes the previous blocked native
path and preserves the tested picture. Dual QSV did not reproduce a large CPU
saving in Kodi. Render usage is effectively similar; decode-engine busy and
sampled service memory are lower in these windows. Keep QSV experimental rather
than changing the default based on this measurement. Seek/transition behaviour
and broader short-scene coverage remain to be checked.

The performance subdirectory contains deployment-specific controllers and the
additive observer/matrix changes used here. These reuse the existing reference
observer modules in an isolated copy. Their private capture-proof dependencies
are not distributed film data; another tester must generate their own matched
capture and substitute explicit proof pins. No frame or RPU data is published.
