QSV BL per-picture HEVC chroma-location metadata candidate

Problem observed on Petunia: dual QSV decode and renderer buffer acceptance
progressed, but native reconstruction rejected undeclared-base-chroma-location.
The test displayed frozen output, captured no frame, and restored the working
19379 binary and runtime/settings. Decoder progress was not playback success.

This candidate extends the existing private qsv_dovi.h picture-token record
with chroma_location. For the real HEVC QSV Dolby path, it reuses FFmpeg's
HEVC VPS/SPS/PPS parsers and reads only the first-slice PPS ID. The retained
PPS selects its referenced SPS; this matches FFmpeg's own HEVC slice parser.
The SPS VUI interpretation matches HEVC set_sps(): explicit codes 0..5 map
to AVChromaLocation 1..6; absent chroma-location signalling in 4:2:0 uses the
format-defined LEFT value. Unsupported format/missing PPS/invalid code fails.
This is not a calibrated or guessed value and adds no software pixel decode.

The value is snapshotted in each submitted picture entry and copied to that
exact returned token's AVFrame. A later parameter-set change cannot replace
the value for an earlier reordered output. Direct QSV-to-VAAPI mapping keeps
the frame properties. Flush clears pending/output entries, while keeping
parameter sets as HEVC decoder flush does; close releases parameter sets.
The native LEFT/TOPLEFT admission policy is unchanged.

CPU fixtures passed: defined default, six explicit locations, two pictures
returned in reverse order after a location change, invalid location, invalid
chroma format, missing PPS, flush, and existing ten-frame IRAP/key association.
Assertions were explicitly enabled; 512MiB/noSwap/CPU1/noGPU fixture.
Peak memory 64544768 bytes. Earlier harness compilation/synthetic-bitstream
mistakes are retained privately; they do not constitute successful tests.

Only private qsv_dovi.h and qsvdec.c change; public ABI and reconstruction
math remain unchanged. Fresh serial library build is in progress. No target
playback, output accuracy, or performance improvement is claimed yet.
