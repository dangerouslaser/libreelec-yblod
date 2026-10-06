# BL QSV picture-association v2 lifecycle experiment

The standalone Saving Private Ryan fixture passed three identical packet windows: initial decode, flush/reseek, and close/reopen/reseek. Each window accepted, returned and paired 725 pictures on both decoders, with known matching presentation timestamps, positive source durations, independent native Dolby instructions and no pending snapshots. Each epoch retained the selected three-picture, nine-plane literal sample comparison through the same strict equality checks.

One genuine mapped QSV-to-VAAPI frame remained owned across flush and decoder close/reopen. Its readbacks stayed identical to the original same-route reference, including transport DTS. The old GPU pool was not released to force the test to fit.

This is standalone decoder/lifecycle evidence, not Kodi playback, display output, Dolby conformance, full-film EOF or performance qualification. No previous-RPU-reference cases occurred. The earlier picture-window reports and failed strict transport-DTS diagnostic remain unchanged in the sibling candidates.

## Comparison boundary

The inherited `picture-association.v2` contract keeps source PTS, known best-effort timestamp, source duration, flags, geometry, color properties, Dolby metadata and literal samples mandatory. Cross-decoder packet DTS is reported separately because FFmpeg defines it as the packet triggering frame return. Each epoch recorded 665 equal and 60 different packet-DTS pairs; three were unknown on both routes. No product DTS was rewritten. Same-route retained-frame immutability still compares DTS strictly.

## Reproduce

Run `python3 run_duration_window_probe_compile.py` from a fresh copied source directory in the pinned SDK layout. It uses 512 MiB, no swap, one CPU and no GPU/network. Fourteen duration cases, pair/property faults, drain/refcount fixtures, twelve base observer methods and seven lifecycle observer methods passed. Expanded negative fixtures reject per-epoch count, duration, pending snapshot, owner, EOF and transport-conservation errors as well as final-report inconsistencies. CPU tests do not substitute for the hardware result.

The hardware controller is `check_picture_lifecycle_qsv_bl_runtime.py`. It requires the exact isolated key-association FFmpeg build, compiled probe and repository identity helpers at its pinned paths, `PRIVATE_INPUT_PATH`, idle Kodi and a fresh output directory/container name. Its names reproduce this recorded attempt and intentionally fail if the attempt already exists.

The hardware allowance is 1536 MiB **for the dual-decoder test only**, with no swap, one CPU, a bounded child deadline and 6 GiB launch/3 GiB abort host-memory safeguards. Peak memory was 1,235,619,840 bytes, with zero memory events and zero swap. Holding a mapped frame can retain an entire old pool; the cap was not raised. The 22.45-second offline run is not a playback-speed measurement.

The full lifecycle report records all three epochs, actual Intel GPU/code identity and clean child termination. Actual typed Kodi admission, packet-duration forwarding and combined BL/EL player presentation remain separate work. Production decoding remains default-off for this experimental route.
