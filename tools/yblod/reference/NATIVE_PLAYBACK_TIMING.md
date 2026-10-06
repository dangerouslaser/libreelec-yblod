# Opt-in native playback stage timings

The C playback context now has additive diagnostics; existing create/frame ABI2
layouts and reconstruction math are unchanged. Diagnostics default off and
perform no clock reads until explicitly enabled.

For a build with `YBLOD_NATIVE_RECONSTRUCTION=1`, the Kodi diagnostic integration
is enabled separately with `DVBRIDGE_NATIVE_DIAGNOSTICS=1` alongside
`DVBRIDGE_NATIVE_RECONSTRUCTION=1`. It reports native stage aggregates every120
successfully released frames. Diagnostics are measurement, not an optimization;
compare the same playback window before/after any proposed change.

All timings are host `CLOCK_MONOTONIC` wall time—not GPU kernel/device time.
The11 buckets are scaler submit, VA wait, combined BL/EL import, preparation
submit/wait, composer submit/wait, YCC submit/wait, bridge and consumer release.
Import counts both actual calls separately. Release covers the full release
operation, including consumer wait, cleanup and context restoration; other
buckets cover their named helper calls only. Metadata/admission/plan construction
and other context switches are not comprehensively included. Their sum is
therefore **not whole-frame renderer time**.

Each bucket records calls, OK/PENDING/failed counts, total wall nanoseconds and
maximum call time. Average call time is `total_wall_ns/calls`, not time per frame.
`completed_frames` counts successful consumer release, not HDMI flips or the
renderer draw-call counter. Pending retries contribute separate API attempts.
Kodi's periodic log instead divides each cumulative stage total by
`completed_frames` and reports `wall_ms_per_released_frame`; this includes any
counted retries and is distinct from the API's average call time. It still is
not a complete frame budget or proof of unique displayed-frame cadence.

`yb_native_playback_diagnostics_enable`, `_get` and `_reset` run on the same owner
thread as playback; reads are not atomic/thread-safe. Enable/reset require an
idle, nonclosing, nonquarantined context. Get may inspect retained quarantine
statistics. Version1 is output-only. Clock errors/backward readings or checked
counter overflow invalidate diagnostics without altering playback or its
quarantine/lifetime decisions. Logs must reject `valid=false` aggregates.

[The host checkpoint](results/native-playback-timing-host-20261006v.json) records
34 synthetic actual-helper checks, strict SDK archive compilation and a
whole-archive SDK link. A fake clock proves default-disabled/no-clock behavior
and exercises counts, arithmetic guards and reset/errors without GPU work.
This is not a production performance benchmark. Its exact source, archive and
executable identities are recorded separately from historical playback results.
