# Explicit enhancement sampling diagnostic

`sampling_contract.py` and `native_sampling_probe.c/.h` separate three things:
the raw carrier word, the requested source position, and an explicitly declared
numeric normalization. They do not choose a production sampler or quantizer.
The probe is CPU-only; it does not emulate GPU floating-point texture hardware.

## Contract and boundary

`SamplingContract(width, height, origin_x, origin_y, step_x, step_y, method,
word_normalization_divisor)` is frozen and strictly validated. Coordinates are
integers or exact dyadic `Fraction`s, with denominators at most 65536 and each
origin/step between −8192 and +8192. At output query `(x,y)`, source position is
`(origin_x+step_x*x, origin_y+step_y*y)`. Query indices are integers 0..8191.
No phase is inferred from matching a capture.

The explicitly supported colour route is native depth 10, fractional bits 6.
This is a declared current Intel convention, not a universal Y416 property.
`word_normalization_divisor` is mandatory, 1..2^32−1. A caller may declare 65472
for the native10/Q6 full-scale diagnostic, or another divisor as a distinct
experiment. The field does not assert actual texture normalization.

The native API borrows one host-u16 colour plane, such as a lossless
`native_y416` unpacker output. It declares complete source dimensions, row
stride in samples and available sample extent. Pitch padding is ignored;
last-row padding is not required. This is not an automatic row-tile interface:
a tile boundary must never silently become an image edge. Alpha is not accepted
as a colour interpretation. Caller allocations must remain accessible, alive,
stable and coherent; no hardware fence or producer synchronization is inferred.

## Explicit operators and results

- `integer-point` accepts only integer source positions; a fractional position
  fails rather than silently choosing a nearest rule.
- `bilinear` is a declared exact two-axis diagnostic operator, **not Annex B,
  an Intel filter specification, or a licensed Dolby rule**.

Both explicitly replicate the true image boundary. Results retain requested
coordinates even when individual taps replicate an edge. No raw word, including
65535, is rounded or nominal-depth-clipped. Native results are unreduced exact
rationals: raw word, raw word divided by 64, and raw word divided by the declared
normalization divisor. A sampled 65535 divided by 65472 remains greater than one.
Inverse NLQ and any transport-to-integer decision are separate stages.

`yb_sampling_probe(plane, contract, queries, batch_count, results, result_count)`
requires equal counts, 1..65536. Dimensions, extents, coordinate bounds, aliases,
alignment and all queries are validated before any output write. Results may
not overlap the full declared source span, either descriptor or query array.
Late invalid queries leave every output untouched. Dyadic bounds keep coordinate
and numerator/denominator arithmetic within the stated C integer widths; no
float approximation or implicit quantizer is used.

For coordinate denominator `D≤2^16`, bilinear raw denominator is `D²≤2^32`.
Its nonnegative weights sum to `D²`, so raw numerator is at most
`65535*2^32 < 2^48`. The largest normalized denominator is
`2^32*(2^32−1) < 2^64`; native denominator is at most `2^38`.
Bounded origin/step numerators and query indices put each coordinate numerator
within ±`8192*2^16*(1+8191)=2^42`, safely inside signed64.

## Named half-pixel illustration—not a default

For the explicit bilinear contract `origin_x=1/2, origin_y=0, step_x=step_y=1`
and raw words `[32768,32784]`, query `(0,0)` yields raw **32776**, native
equivalent **512.125**, and the diagnostic ratio **32776/65472** if that divisor
is declared. These are not the original raw pixel or a quantized 10-bit code.
Also, 32768/65472 is not exactly 1/2, and dividing by 65535 is different again.

This named illustration helps distinguish surface storage from a possible
later sampled EL value. It does not establish that a loaded Kodi shader uses
these coordinates, linear sampling or this normalization. Static source
conditions and independently observed GPU samples belong in separate evidence.

Run `python3 -m unittest -v test_native_sampling_probe` to compile the native
probe with strict warnings and compare against the stdlib `Fraction` oracle.
Nine tests exercise all low-six-bit values, overshoot, negative/high-precision
dyadics, mirrored geometry, edges, padded canaries, alias and overflow failures,
late invalid queries, the maximum batch and the illustrative half-pixel case.
No GPU job, SK4 fit, playback change or selected rounding policy follows.

Optional `YB_SAMPLING_TEST_CFLAGS` supplies explicitly requested compiler flags,
for example `-fsanitize=undefined -fno-sanitize-recover=all` on Linux. This only
changes the temporary test library, not an engine or production build.

`test_native_sampling_independent.py` adds two tests, including 1,440 seeded
two-dimensional comparisons against a separately written weighted-sum Fraction
oracle. All eleven tests passed on Ollie with undefined-behaviour sanitization
and recovery disabled, under a 512 MiB no-job-swap scope. This is CPU diagnostic
validation, not a GPU texture precision or playback-performance measurement.
