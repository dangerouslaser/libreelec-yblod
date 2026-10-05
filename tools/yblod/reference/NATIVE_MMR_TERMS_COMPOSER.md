# Avoid redundant colour-term clearing

This separate candidate removes only `terms[21]` zero-initialization from the
prepared per-code-decision backend. Compile `native_mmr_terms_composer.c`
instead of `native_mmr_prepared_composer.c` or `native_mmr_composer.c`, never
multiple backends together. The existing header/API and all validation remain.
The reference, default build and Kodi playback are unchanged.

## Why the change is exact

Preparation stores a coefficient index only for a nonzero coefficient, and sets
`order` to include that coefficient's row. Thus every active index is strictly
less than `7*order`. Processing assigns every term in every row through that
order before reading any active index. An order-zero/constant-only segment has
zero active coefficients, hence no term reads. This invariant holds for both
the proved narrow accumulator and the signed-wide fallback. No floor, clamp,
coefficient, accumulation order, ownership or rejection guard changes.

Independent review checked that invariant and the one-line implementation
diff. Undefined-behaviour checks alone do not detect uninitialized reads; the
invariant and independent coverage are the relevant additional evidence.

The prior SDK hot function cleared 42 dwords (168 bytes) per MMR sample using
`rep stos`. The new hot function has no `rep`, `stos` or `memset` and shrinks
from 2470 to 2422 bytes. Both reserve 384 bytes of stack: this removes redundant
writes and clearing setup, not the term array or stack memory allocation.

## Actual direct VM comparison

[The aggregate report](results/native-mmr-terms-comparison-vm-20261005a.json)
records six sequential fresh process cohorts on the same hash-verified 4K
whole-code frame, with pair orders prepared/terms, terms/prepared,
prepared/terms. Both binaries use the same SDK and strict flags. Each cohort
retains full untimed stage equivalence, warmups and three internal
reference/backend timing pairs. These are paired process cohorts, not a
single-process alternating optimized-frame harness.

| Pair | Prepared median | New median | Less time |
| --- | ---: | ---: | ---: |
| 1 | 243.215 ms | 212.616 ms | 12.6% |
| 2, reverse order | 241.105 ms | 212.246 ms | 12.0% |
| 3 | 242.440 ms | 207.314 ms | 14.5% |

The candidate won all three pairs. Pooled nine-sample medians were 242.440 ms
and 212.246 ms: about 12.5% less diagnostic processing time. This is one input,
not a statistical-significance or universal-media speed claim.

All six untimed gates matched 49,766,400 stage values across 191 dispatches;
all expected component counts completed. Timed checks cover the final chunk
only. Preparation and teardown are included; shared input loading/scratch
allocation, GPU scaling, decoding, colour conversion and display are excluded.
Each wrapper checked input, binary, wrapper and runtime identities before/after.

Each scope enforced 512 MiB/no swap with zero high/max/OOM/OOM-kill events,
zero observed swap and Kodi active before/after. Retained pre-exit memory peaks
ranged from 57,163,776 to 57,696,256 bytes. CPU quota controller data was
unavailable. Snapshots are not final lifetime peaks, process RSS or GPU memory.
No movie pixels, metadata coefficients, input hashes or private paths are
published. This is not playback FPS, independent DV conformance or SK4 matching.

## Build and tests

Use the build command in NATIVE_MMR_COMPOSER.md, substituting only the composer
source and a distinct executable output name. The unchanged paired diagnostic
retains its schema; the surrounding report identifies the linked backend.

```sh
python3 -m unittest discover -s tools/yblod/reference -p 'test_native_mmr_terms_composer.py'
```

All 18 tests passed normally and under undefined-behaviour checks. Seventeen
inherited independent contracts cover the unchanged C/Python equations, sparse
highest powers, constant-only, random dense coefficients, wide cancellation,
mixed segments and rejection/ownership guards. The added test exercises every
one of the 21 single-active basis/power positions, both coefficient signs,
endpoint clamping and whole 8/10-bit code domains. Python is test orchestration;
the implementation is C.
