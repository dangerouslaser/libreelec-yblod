# Native informative Annex B diagnostic

`native_annexb_probe.c/.h` implements the explicitly named informative CCM
Annex B enhancement resampler. It is a standalone arithmetic diagnostic, not a
selected production backend, a licensed Dolby filter assertion, a physical
chroma-registration adapter, or a replacement for QuickSync/AMD offload.

The exact public tap and literal-answer contract is documented separately in
[ANNEX_B_RESAMPLER_VECTORS.md](ANNEX_B_RESAMPLER_VECTORS.md). Y and Cb/Cr have
distinct vertical filters. Vertical precedes horizontal, each pass rounds with
its own half-divisor bias and mathematical floor, then clips to unsigned16.
Negative division is implemented portably, not by relying on signed right shifts
or truncating C division. Input samples remain host-u16 integers; fractional
Y416 words are not assigned this coded-EL interpretation automatically.

## Bounded global-rectangle API

`yb_annexb_probe(plane, component, mode, global_rect, output,
requested_pixels, scratch, scratch_samples)` borrows one complete component
plane. Source dimensions are 1..8192, with declared row pitch and accessible
sample extent. Caller allocations must be stable, alive, coherent and accessible
throughout the call; this is not a hardware-fence or DMA ownership interface.

The two modes are explicit: vertical-only has native width and doubled height;
two-pass has doubled width and height. The requested rectangle uses **global
coordinates** in that mode's output domain. Every filter tap replicates only
the complete input image boundary. A rectangle edge, output row-strip boundary,
or pitch padding is never substituted for that boundary.

Scratch is exactly one native-width row of u16 samples, supplied by the caller.
The kernel computes the rounded/clipped full vertical row, then writes only the
requested output columns. It performs no allocation or Python pixel work.
`requested_pixels=rect.width*rect.height` must be 1..65536. Output storage is
a separate extent: `(rect.height−1)*output.stride_samples+rect.width`; last-row
pitch padding is not required. Extra declared storage/padding is preserved.

For a 1920×1080 component plane producing width3840, a 16-row rectangle requires
61,440 output samples (122,880 bytes) and 1,920 scratch samples (3,840 bytes).
The complete unpadded borrowed input is 4,147,200 bytes. No full enlarged frame
or full vertical intermediate is required. These are buffer sizes, not a
guaranteed total process/cgroup peak; caller runtime and file cache still count.

## Validation and arithmetic bounds

All descriptor, geometry, extent, count, address-overflow and alignment checks
finish before **any scratch or output write**. Both writable regions must be
disjoint from the complete declared source span, all three descriptors and each
other. Invalid calls leave both arrays unchanged. Allocation accessibility and
external synchronization remain caller obligations.

For u16 values, the horizontal absolute coefficient sum is 6192, bounding its
sum plus bias by `6192*65535+2048 < 2^29`. The Y vertical absolute sum is 152,
so `152*65535+64 < 2^24`; chroma has `256*65535+128 < 2^24`.
The implementation uses signed64 accumulation. Bounded global dimensions keep
tap indices small; footprint products and pointer spans are explicitly guarded
before use. The stated 16-bit clipping is not silently replaced with a native10
maximum: the literal native10 fixture still produces vertical value1095.

## Verification

Run `python3 -m unittest -v test_native_annexb_probe`. Eight tests compile the C
probe with strict warnings and check hand-derived vertical/final Y/C answers,
the per-pass rounding and edge-ringing discriminators, seeded independent
Fraction comparisons, stitched/partial global rectangles, source/output padding,
storage clipping, aliases, invalid-call preservation, and a width3840 bounded
rectangle plus the maximum batch. Optional `YB_ANNEXB_TEST_CFLAGS` supports a
temporary UBSan test build on Linux. No GPU job or production policy changes.

The eight native tests and four literal-answer tests passed together on Ollie
with undefined-behaviour sanitization and recovery disabled, under the unchanged
512 MiB no-job-swap cap. This checks arithmetic and API boundaries, not playback
throughput or a hardware scaling backend.
