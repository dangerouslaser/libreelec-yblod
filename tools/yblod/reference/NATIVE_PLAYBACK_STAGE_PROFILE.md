# Native playback stage profile

This connected-TV 1917 observation used a measurement-only build, not either shader optimization. Native reconstruction remained eligible and reached 1,320 successfully released frames at the last logged snapshot. Service identity remained unchanged; no fallback/quarantine failure marker appeared. These commits are not unique source frames or HDMI flips.

Eleven logs contain cumulative host-helper wall means rounded to 0.001 ms. The parser estimates a later window only between available snapshots: release240 at13.279 seconds to release1200 at63.998 seconds relative to the first-frame log. The per-stage rounding bound is ±0.00075 ms per released frame. It does not recover original nanosecond totals.

Largest estimated helper buckets were composer completion wait16.38525 ms, consumer release7.22125 ms, YCC completion wait5.15275 ms, VA wait4.01075 ms and preparation wait2.08325 ms. These are host-call wall measurements including waiting, not exclusive GPU kernel times. Imports aggregate both BL and EL per released frame. Colour-only rendering and other renderer/decoder work are not a complete measured frame budget; summing buckets does not establish playback FPS.

Approximate health10–70second windows recorded baseline drop+1/skip+7 versus measurement drop+5/skip+7, with no logged stalls and normal speed. Interval-weighted renderer diagnostics were63.9831% and63.2624%. Kodi-client DRM render busy diagnostics were64.2901% baseline and63.2606% measured. Baseline lacks a saved monotonic observer start and uses ordinal2second sample anchoring; measured intervals use the saved exact anchor. Interval sets differ slightly:60.309 versus58.254seconds. This is not evidence of improvement; matched repeats are needed.

Saved memory figures describe the entire Kodi service and different process histories, not native-engine allocation or proof against leaks. Whole-service peak was about1.85GB versus2.05GB in the earlier control. The saved report retains exact values and post-stop current usage.

The parser rejects invalid/nonfinite/negative means and nonmonotonic/non120-multiple release counts, suppresses window inference after identity changes or failures, and publishes no raw paths/PIDs/log payload. Tests cover production valid=1 markers, precision, invalid data and saved evidence. No display colour-accuracy conclusion is made.
