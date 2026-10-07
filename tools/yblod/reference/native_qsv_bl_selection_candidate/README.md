# Profile-scoped base-layer QSV selection fix

The interactive dual-QSV build's environment flag previously rejected every
stream outside its supported Profile 7 class. This made Profile 8 (and other
formats) fail before a normal codec could open.

`qsv-stream-selection.patch` changes only route selection: enable the experimental
BL QSV decoder when the flag and native reconstruction are enabled, native
output is eligible, the stream is HEVC Profile 7 with an enhancement layer,
orientation is zero, and software decoding is not forced. Otherwise leave
`pCodec` unset and continue through Kodi's existing decoder selection. If an
eligible stream specifically requests QSV but that decoder is missing, keep the
existing explicit failure; do not silently change the experimental P7 route.

The patch applies to the validated complete-frame-handoff candidate, not the
unqualified nearest-neighbour candidate. FEL scaling, reconstruction shaders,
metadata handoff and FFmpeg/VPL library versions are unchanged.

`test_stream_selection.py` extracts and compiles the actual source selection
block against a small C++ fixture. All 1,025 cases pass, including disabled or
missing flags, non-DV/Profile 5/Profile 8, non-HEVC, rotated/software streams,
missing EL, and unavailable QSV decoder. This is route-logic evidence, not
playback or colour conformance. The fixture requires Python and a C++17 compiler.

`prepare_build_qsv_kodi.py` and `source-manifest.json` retain the pinned SDK,
source checks, four-worker/4 GiB/no-swap limits and memory/disk reserves used by
the validated build. Paths are workstation-specific. Build and P8/P7 playback
results will be recorded separately after testing; no pixel/RPU data is included.
