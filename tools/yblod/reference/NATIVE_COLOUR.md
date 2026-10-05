# Native colour-coordinate component

`native_colour.c` and `native_colour.h` provide native C colour arithmetic for
the standalone engine. Python's `colour_stage.py` is a separate comparison
oracle, not the implementation. This component is not yet wired to Kodi and
does not select a chroma filter, fractional EL precision rule, Dolby transport
target or production output policy.

## Explicit inputs and operation order

The initializer requires all source/target 3x3 matrices and offsets, the
project's declared 4096 code scale, and one of these explicit PQ policies:

- `YB_PQ_REJECT_OUTSIDE_UNIT`: reject PQ inputs outside 0..1.
- `YB_PQ_EXTEND_POSITIVE_NEGATIVE_TO_ZERO`: extend positive PQ inputs, replace
  negative PQ inputs by zero, and reject decode poles/nonfinite results.

The second policy is an experimental continuation, not a licensed rule outside
the published PQ domain. No target matrices, display adaptation or hidden RGB
gamut bound are supplied. Target matrices must be invertible; their inverses
are computed once during initialization. Source matrices need not be invertible.

Each finite input component must remain in 0..4095. Fractional components are
allowed only as the result of a separately declared chroma-expansion contract;
this does not choose fractional enhancement reconstruction behavior. The stage
subtracts source offsets, transforms source nonlinear coordinates, decodes PQ,
transforms to the common linear basis and then the target linear basis, encodes
PQ, transforms target nonlinear coordinates, adds target offsets, and finally
rounds/bounds target codes. Final rounding is `floor(value*4096+0.5)` followed
by the 0..4095 output bound, not an intermediate source clamp.

The result retains all four intermediate triples plus the three target codes.
Active-area masking, tunnel packing, metadata provenance, RPU parsing, HDMI
signalling and display tone mapping remain outside this API.

## Native API, memory and failure behavior

Create a configuration with `yb_colour_init`, keep it unchanged, and call either
`yb_colour_sample` or `yb_colour_process_chunk`. Configuration storage belongs
to the caller. Validation checks initialized/finite fields but does not
authenticate a forged structure or recompute its inverse after caller mutation.
JSON/FFI adapters must reject wrong original value types before conversion;
the C API sees numeric values, not their JSON provenance.

Chunks contain 1..65536 triples. Input stride is measured in doubles, output
stride in result structures. Both must be explicit; their normal values are
three and one. The output must not overlap input or configuration memory.
Pointer alignment and address-range overflow are checked; actual allocation
sizes, pointer validity and stable buffer ownership remain caller obligations.

Every destination remains unchanged on a conversion failure, including a late
matrix/PQ-domain error. The chunk implementation uses a temporary result array
bounded to 65536 results, about 6.5 MiB on the tested ABI, and publishes only
after all samples succeed. This initial safety implementation allocates once
per chunk; reusable caller workspace is a possible optimization after tests.
There are no whole-frame working arrays. ABI/version/size queries let adapters
reject incompatible libraries. This is not a GPU emulator or a performance
claim about full playback.

## Build and arithmetic evidence

```sh
cc -std=c11 -O2 -fPIC -shared -Wall -Wextra -Werror \
  -Wconversion -Wshadow -fno-fast-math -ffp-contract=off \
  native_colour.c -lm -o libnative_colour.so
python3 -m unittest test_native_colour
```

The implementation uses double precision and the platform's math library.
Fast-math and floating-point contraction must remain disabled. Platform/libm
differences can affect values near a quantization boundary; empirical exact
code agreement on a corpus is not universal byte equality or a licensed-player
accuracy result.

Seven tests compile temporary libraries and verify published-domain PQ values
against the separate 60-digit Decimal oracle, eight transport triples against
independent known answers, and 798 identity/nonidentity/fractional-input triples
against the Python colour stage. Intermediate tolerance is relative 2e-11 or
absolute 2e-12; target codes agree exactly on these fixtures. Tests also cover
nonsymmetric inverse orientation, offsets, explicit policies, positive/negative
domain excursions, singular/nonfinite configuration, final-only clipping,
strided padding, the maximum chunk size and unchanged outputs on late failure.

Initial verification used Apple Clang 17 on arm64. All 17 native integer/colour
tests also passed with UndefinedBehaviorSanitizer and recovery disabled.
Further target/compiler checks and measured end-to-end benchmarks are required
before making deployment or throughput claims.

Next connect the bounded native stages to the prepared-frame adapters, preserve
explicit configuration/provenance in their reports, and compare every output
stage against the oracle before experimental playback integration.
