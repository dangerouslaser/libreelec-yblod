# Enhancement route selection correction

The dual-QSV renderer incorrectly required an enhancement-layer QSV route
even for Profile 8 streams, which have no enhancement layer. The prior
decoder-selection correction allowed decoding, exposing this second guard.

`PrepareHardware` now requires enhancement-route proof only when an
enhancement frame is present. Invalid flags and invalid route evidence still
fail. FEL proof remains required; missing FEL validation elsewhere is not
relaxed. Reconstruction, colour, scaling and metadata math are unchanged.

`test_route.py` extracts and compiles the actual source condition and checks
24 combinations plus explicit no-EL/FEL assertions. These passed locally.
This is a guard regression test, not a claim of successful movie playback.

`build_incremental.py` reuses the isolated selection candidate's pinned SDK
mounts, with four workers, a 4 GiB RAM limit and no swap/network/GPU access.
Playback qualification remains pending until the rebuilt binary is tested.
