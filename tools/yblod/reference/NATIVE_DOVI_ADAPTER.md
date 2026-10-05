# Decoder metadata to owned integer instructions

This standalone optional adapter copies decoder-expanded FFmpeg Dolby Vision
metadata into the existing integer composer's configurations. It does not parse
an RPU, require JSON or libdovi, change Kodi, or introduce a dependency into the
arithmetic core's build. No rendering or production default is changed.

## Exact boundary

```c
int yb_dovi_to_integer_configs(const void *side_data, size_t bytes,
                               yb_dovi_integer_instructions *output);
```

Compile `native_dovi_adapter.c` against the **actual matching patched**
`libavutil/dovi_meta.h`. Do not supply replacement FFmpeg structs: these layouts
are explicitly not stable public ABI. Validate the allocation's size, address
range, alignment, offsets, region overlap, extension count and stride before
calling its accessors. An empty extension array is accepted at a correctly
bounded/aligned end position; no display-metadata payload is required here.
Colour/extension-region layout is checked, but their contents are not converted
or semantically certified by this arithmetic adapter.

The function copies into a zeroed candidate and commits only after success.
Failure leaves the destination unchanged. Output/source overlap is rejected;
the caller must supply accessible, coherent, stable allocations. There is no
retained FFmpeg pointer or new reuse-state cache.

FFmpeg's decoded pivots are already cumulative, its polynomial degrees and MMR
orders are already expanded, and its signed/unsigned coefficient fields already
contain the combined fixed-point integers. They are copied without floating
normalization, sign reinterpretation, another pivot accumulation or another
order increment. Only active entries are copied: unused source slots may retain
previous data and are deliberately ignored. Unused destination entries are zero.

The initial subset requires fixed-coefficient RPU type 2/format 18, normalized
idc 1, no extended mapping, one mapping region, native 8/10 and output 10/12.
The actual FFmpeg layout exposes at most nine pivots, not the native core's 17.
All supported polynomial/MMR orders use the core's validation. Unknown active
methods and invalid active ranges are rejected, never clipped into acceptance.

With residuals enabled, the adapter requires the supported single-piece
linear-deadzone NLQ and native endpoint pivots, copies all four NLQ fields, and
checks the EL-dependent denominator minimum. With residuals explicitly disabled,
all source NLQ fields are ignored and destination NLQ is zero. The mapper-only
denominator 13–32 remains available in that branch; no missing-EL fallback or
automatic MEL classification is introduced.

Both spatial-resampling flags are checked as 0/1 and exported as declarations;
no filter or registration is executed. An explicit chroma-filter flag of 1
returns `UNSUPPORTED_PREPARATION`: this version has no corresponding tap
contract. That means unsupported, not malformed metadata. The coefficient copy
itself could be defined separately from that preparation obligation.

## Caller responsibilities and limits

The output is ready for a caller to validate alongside its prepared whole-code
frame, not an assertion that a raw decoder surface is ready for composition.
The caller must check stream profile, BL/EL association, frame identity, sample
depths, geometry, phase, transfer characteristics and producer readiness, then
use the existing integration boundary. Enabled-but-missing EL is rejected by
that boundary; it is not something this metadata-only function can observe.

The public FFmpeg header does not identify stream Profile 7 or FEL. Exported
`source_rpu_profile`/`source_rpu_level` preserve RPU syntax labels only. FFmpeg
resolves previous-mapping references before attaching expanded metadata; the
caller still owns decoder state and resets across seeks. CRC checking is
conditional in the inspected decoder and is not guaranteed by side-data
presence. This adapter proves neither fresh CRC verification nor authenticity.

## Source evidence

Inspected actual build tree: `ffmpeg-9.0.2` under the existing LibreELEC Generic
build on Ollie. The SDK and build-source `libavutil/dovi_meta.h` hashes match:

- Header, lines 87–164 and 350–393:
  `f860511cb8be3c992b4ef7da6747d8dc9670d64d276aeab3a7e6867112857a02`.
- `libavcodec/dovi_rpudec.c`, lines 33–87, 90–122, 534–655, 747–757:
  `6fc14110e0ad8ccc0359ebc09fae9b8a3bfe3bf3e09e838384cc5ef5b0f27df8`.
- Actual allocator `libavutil/dovi_meta.c`, lines 37–63:
  `e504b834735e11b3a3524408a82d42330571619c5729ca9dee4d2e2f5c7ba4a0`.

The decoder combines signed whole parts with fractional bits before this
boundary, and converts original floating coefficients to fixed values. That
floating-origin subset is deliberately unsupported here rather than silently
claiming unchanged source precision.

## Synthetic validation and reproduction

`native_dovi_adapter_probe.c` allocates each of 40 fixed public synthetic fixtures
using the real `av_dovi_metadata_alloc()`. Twelve should succeed and 28 should
reject. It verifies unchanged source storage and unchanged failed output,
canonical unused destinations, then destroys the source before exercising the
copied configuration through the existing C arithmetic core.

Fixtures cover negative fixed coefficients, cumulative pivots, all MMR orders,
poisoned inactive slots, disabled poisoned NLQ, the disabled denominator 13 case,
spatial declarations and empty extensions. Rejections cover active unsupported
metadata, malformed regions, truncation, aliasing, null/misaligned/wrapping
pointers and oversized byte declarations. No actual film or RPU is embedded.
The emitted configuration independently checks the two spatial flags. Other
copied header labels are source-reviewed but are not separately emitted or
varied by these fixtures; this is not an exhaustive all-header-field test.

Build with the matching SDK compiler/header/library, for example:

```sh
"$CC" -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
  native_dovi_adapter.c native_dovi_adapter_probe.c native_composer.c \
  -lavutil -o native_dovi_adapter_probe
YB_DOVI_ADAPTER_PROBE=/path/to/reviewed/native_dovi_adapter_probe \
  python3 -m unittest -v test_native_dovi_adapter
```

`test_native_dovi_adapter.py` independently builds the expected configuration
and compares the C stage outputs with the Python integer reference. It includes
literal negative-cap/fractional-coefficient answers and strict-type/tamper
checks. Without an actual-header executable or matching published checkpoint,
the actual C tests explicitly skip: the three host-only checks are not a native
execution result. The published checkpoint below supplies actual SDK execution
evidence for replay; replaying it does not run a fresh native binary.

## Measured SDK checkpoint

[The synthetic checkpoint](results/native-dovi-adapter-cpu-20261005b.json)
records 40 normal and 40 undefined-behaviour-sanitized executions on the LibreELEC
VM. Both binaries used the real patched FFmpeg header and allocator, built with
GCC 16.2 and strict warnings. Every process exited successfully without stderr;
all 40 normal/sanitized stdout files were byte-identical. Each build accepted 12
fixtures and safely rejected 28. The independent Python reference reproduced
every emitted arithmetic stage for the accepted fixtures. Eight focused replay
and host-validation tests pass with no skips using this published checkpoint.

The scope enforced 512 MiB with swap disabled. Its in-script `memory.peak`
observation was 6,914,048 bytes (6.59 MiB); this is a snapshot before process exit,
not a measurement of the final scope-lifetime peak. The saved swap observations
and memory pressure/OOM counters were zero. Kodi remained active before and
after; no GPU, playback or display changes were made. The sanitizer runtime was
private to its child process via `LD_LIBRARY_PATH`; no installed library was
replaced, and the recorded runtime-library hashes remained unchanged.

The report separately pins the five executed C/header inputs, the exact cohort
script, binaries, FFmpeg header and loaded library. Its analysis pins identify
the replay tests and this document prepared after execution, not extra executed
native inputs. A separate sanitizer loader preflight and an earlier interrupted
attempt (the host lacked `cmp`) are preserved privately and are not counted in
the successful 40+40 cohort. All published samples and metadata are synthetic.

No full-frame adapter handoff, actual decoder-frame pairing, playback,
fractional EL handling or licensed conformance is claimed by these fixtures.
