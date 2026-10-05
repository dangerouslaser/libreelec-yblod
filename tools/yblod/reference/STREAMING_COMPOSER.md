# Chunked standalone prepared-frame composer

`streaming_composer.py` assembles independent base mapping, enhancement
correction and final composition into a usable offline prepared-frame runner.
It does not decode a movie, scale layers, convert to RGB, output HDMI metadata,
or replace Kodi playback. Its input manifest describes already aligned planar
4:2:0 layers and an explicitly prepared luma guide when MMR requires one.

## Run

From the repository root, with fresh destination paths:

```sh
mkdir -p target
python3 tools/yblod/reference/make_demo.py target/stream-demo-input
python3 tools/yblod/reference/streaming_composer.py \
  target/stream-demo-input/frame.json target/stream-demo-output
```

The existing reference's manifest validation is reused for frame identity,
format and metadata checks. Pixel arithmetic uses `base_mapping_stage.py`,
`nlq_stage.py` and `composition_stage.py`, not the reference's mapper,
enhancement reconstruction or final composition functions. Reusing validation
is explicit: this is independent arithmetic, not an independent RPU parser or
fully independent input-validation implementation.

## Memory, output and failure behavior

Input and output are processed in bounded chunks, not whole-plane arrays.
The default is 4096 samples per chunk; the API accepts 1 through 65536.
Memory depends on chunk size and the small manifest, not frame pixel count.
The manifest read has a separate 8 MiB byte limit. Use `--chunk-samples N` to
declare a different chunk size; invalid sizes are rejected.
This is still an intentionally slow Python validation path, not a real-time
playback performance claim.

All three channels produce the same diagnostic stages as the original runner:
mapped base (unsigned 16-bit), correction and unrounded sum (signed 32-bit), and
reconstructed output (unsigned 16-bit). Values are written explicitly little
endian. Signed dump-storage overflow is an error, not an implicit clamp or
wraparound. Input depth, exact plane lengths and component counts are checked.

The output directory must be new. Its completion report is written last, only
after successful input consumption and output closure. Failures may leave
partial diagnostic files in that new directory, but no completed report.
No previous results are overwritten or automatically deleted.

Input hashes and exact implementation/helper hashes are recorded. Changes to
an opened input's file metadata are checked during reading; this is not an
immutable snapshot guarantee. Do not modify input bundles during a run.

## Evidence and remaining decisions

`test_streaming_differential.py` compares every stage byte, stage summary and
input hash with the unchanged reference across chunk sizes 1, 3 and 65536.
It covers 8/10-bit inputs, 10/12-bit outputs, polynomial interval boundaries,
all three MMR orders, channel-specific correction parameters, binding limits,
and explicitly disabled enhancement processing.

On Ollie, 563 reference tests and 8 accuracy tests passed (571 total, no skips)
under a 512 MiB ceiling with job swap disabled. The public CLI smoke test also
ran with chunk size 3; all twelve output stage files matched the old runner
byte-for-byte. Its source/input-pinned synthetic report is
`results/streaming-demo-v1.json`. Bounded read and write sizes are instrumented
in the failure/IO tests; no actual peak-memory or playback-speed claim follows.

The subsequent full-HD check and measured process-memory results are recorded
in `STREAMING_FULL_HD_RESULTS.md`, together with the synthetic diagnostic
colour-path bridge. These do not change the arithmetic or colour policies.

These are synthetic prepared inputs, not film capture data, licensed-player
ground truth or proof of Dolby conformance. Fractional hardware-scaled samples
still need an explicit input contract; they are not silently rounded by this
runner. Intel/AMD hardware scaling remains a separate upstream operation.

Next validate larger prepared frames within a memory ceiling, connect the
remaining preparation/colour stages with explicit contracts, and only then
port tested arithmetic into the accelerated playback path.
