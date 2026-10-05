# Native pipeline direction

C is the intended playback implementation. Python is the readable reference,
fixture generator and test harness, not a required per-pixel playback engine.
Implementation language and execution device are separate decisions: a C host
can still dispatch hardware scaling and GPU processing. A CPU C rewrite alone
does not establish real-time 4K performance.

`NATIVE_BUILD.md` describes the Python-free static library, installed package
and native smoke tests. Its LibreELEC-target binary has been built on Ollie and
run on the Petunia VM without changing Kodi. `NATIVE_KERNEL_RESULTS.md` isolates
integer C timing from the diagnostic Python/file-output overhead.

## Current components

- `native_composer.c`: standalone integer base mapping, enhancement correction
  and final combination, with a bounded same-count planar chunk API.
- `native_stage.py`: offline build/load and chunk adapter, not future playback
  architecture. The C API can be called directly by a native player.
- `streaming_composer.py --backend native`: every-stage frame dumps for checking
  arithmetic and recording build provenance. No hardware surface is accepted.
- `native_colour.c` implements colour conversion separately in C, with the
  opt-in `colour_frame.py --backend native` diagnostic adapter. Explicit target
  coordinates and out-of-range policies remain diagnostic choices; these do
  not implement complete Dolby display management.
- `native_y416.c` preserves raw scaler words losslessly; the separate precision
  probe compares explicitly named alternatives without selecting a default.
- `native_gpu_probe.c` and its integer shader are isolated desktop-GL diagnostics,
  not a Kodi backend. The polynomial/MMR/NLQ/composition corpus matched the C
  reference exactly on Petunia. See [NATIVE_GPU_PROBE.md](NATIVE_GPU_PROBE.md);
  The fractional hardware frontend remains outside that test.

## Hardware boundary: preserve information first

The prepared-frame input and hardware enhancement output are different contracts.
The current integer composer consumes registered planar 4:2:0 whole codes.
The Intel path produces full-resolution packed 4:4:4 Y416, with little-endian
U/Y/V/A words and fractional sample significance in the low bits. Existing
tests measured fractional values and ringing: those bits are not padding.

Two decisions must remain separate:

1. Pixel grid and registration: which locations each component represents and
   when any sampling/filtering occurs relative to enhancement correction.
2. Precision: how fractional values enter the correction calculation, and what
   happens outside the nominal native-code range.

A lossless surface view/unpacker should retain every word and declare stride,
dimensions, byte order, component order, grid and value significance. It must
not implicitly shift away fractional bits, clip ringing, or convert 4:4:4 to
4:2:0. Buffer lifetime and completion synchronization stay explicit in a later
hardware adapter; a CPU diagnostic buffer does not prove DMA/GPU ownership.

Possible precision experiments include a strict whole-code gate, separately
named rounding models, and an explicitly fractional arithmetic extension.
None is selected as licensed behavior or as a production default merely because
it resembles the SK4. Rounding can create new zero-correction intervals near
neutral and invalid endpoint codes; fractional extensions are not equivalent
to the tested integer specification.

## Integration order and remaining gaps

1. Verify each native component against independent reference cases, then real
   prepared frames. Preserve compiler/source/library hashes and bounded memory.
2. Preserve raw scaler output losslessly and test registration/precision models
   independently. Keep Intel offload; retain a backend-independent contract for
   AMD without claiming untested AMD hardware coverage.
3. Join the native stages in the playback path without changing HDMI packing,
   metadata handling or successful-presentation ownership in the same step.
4. Measure actual playback: missed frames, frame-time distribution, memory and
   GPU load, not just offline stage-dump timings.
5. Investigate remaining SK4 differences by stage and documented behavior.
   Device captures are comparison evidence, not definitions of correct maths.

The current real-frame rewrite reproduces the previous diagnostic output; it
has not reduced the SK4 colour gap. Fractional scaler treatment, chroma sampling,
complete display management and capture association are still open. Archived
SK4 comparisons use a visible counter, not proven matching driver timestamps.
Fresh capture may require confirmation of the TV's visible state.
