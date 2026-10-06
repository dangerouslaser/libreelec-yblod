# EL-only QSV playback comparison

This experiment changes only enhancement-layer decoding, not base-layer decoding, scaling, reconstruction, colour math or HDMI output. Both sides use the same candidate and isolated FFmpeg/VPL libraries. The QSV decoder uses `async_depth=1`.

The completed Saving Private Ryan test uses four 180-second windows at 1200 seconds, in VAAPI/QSV/QSV/VAAPI order. Native planar and direct packed output are enabled; batching and immutable instructions are disabled. This batch0 fixture differs from the retained batch1 playback configuration. Subtitles are temporarily disabled and their original enabled/index state is restored after every case.

| Weighted measurement | VAAPI EL | QSV EL |
|---|---:|---:|
| Whole Kodi CPU, percent of one core | 15.89% | 16.84% |
| GPU render | 29.77% | 29.82% |
| Decode engine, capacity-normalized | 5.33% | 5.31% |
| Video processing engine | 9.51% | 9.50% |
| Whole Kodi service peak | 1.61 GiB | 1.88 GiB |

All four cases have zero observed drops/skips/stalls, exclusive measured native-planar/direct-packed preparation, verified actual decoder routes and normal process shutdown. GPU work is effectively unchanged; CPU and service peak memory increased. This is not an efficiency improvement in this scene. Service memory includes all Kodi allocations and lifetime-high-water accounting, not only decoder memory. Controller memory is reported separately.

The three-frame accuracy admission combines cryptographic canonical RGB/packet equality with literal raw EL sample equality on the actual target, exact source timestamps and RPU association, residual-active metadata, shared-runtime code checks and actual host/GPU identity. It does not establish whole-film conformance, a quality improvement, or complete Dolby Vision/display accuracy. Transport update IDs and their validated CRCs are normalized; arbitrary pixel or payload differences are not tolerated. No raw frame export is needed for the distributed canonical comparison.

Normal process shutdown does not establish successful display restoration. The known preexisting `output restoration failed; retaining scanout state` warning occurred in all four cases.

## Tooling

`el_qsv_canonical_qualification.py` admits the explicit canonical proof schema without changing historical literal comparison gates. `run_el_qsv_canonical_matrix.py` reuses the existing matched-scene matrix and actual-use validators. `observe_el_qsv_active_movie.py` captures code-library identity before the measured window, ties it to every measured process generation, and uses the signal-safe subtitle fixture. `run_el_qsv_observer_owned.py` gracefully terminates only its owned observer and restores recorded subtitle state before Kodi rollback. `summarize_el_qsv_canonical_playback.py` requires all four finalized cases and validates engine sets/capacities before weighting CPU/GPU by actual durations.

The completed deployment used a reviewed private per-boot launcher and guarded top-bind replacement; its original binary, runtime, exact override, mount-layer count, launcher and idle state were restored. These tools are not an unattended universal installer. Reproducing the run requires adapting deployment paths and independently verifying actual code/runtime/host/source identities. The subtitle recovery record is private and must remain available during cleanup. Accuracy checks must precede performance runs; disable output captures during measurement.

Public JSON files contain scalar evidence only. Private source stat records, runtime maps, capture paths, raw pixels and RPU data are not published. Mock tests cover helper contracts, not hardware decoding. The five summary tests are local CPU tests; the thirteen observer/cleanup tests additionally ran in a 512 MiB/no-swap/one-CPU/no-network/no-GPU container.
