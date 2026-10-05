# Experimental exact whole-code cached composer

`engine/experimental/native_cached_composer.c/.h` is an optional C backend,
not a replacement for `engine/src/native_composer.c`. The reference remains
unchanged. No fractional input rule, chroma registration, GPU ownership, colour
processing or playback integration is selected. Default engine CMake does not
include this backend.

## Owned plan and exact tables

ABI version 1 provides opaque plan/frame handles and size queries. Create a
plan with validated mapping metadata, exactly three NLQ configurations when
enhancement is enabled, and output depth 10 or 12. Disabled enhancement is
explicit: NLQ and enhancement input pointers must be NULL, not ignored extras.
Configuration is copied into owned storage and cannot be edited through the
public API. Replacing caller metadata does not update an existing plan; create
a new plan when applicable decoded instructions change.

For each all-polynomial component, table entries for every native 8- or 10-bit
code are generated using the unchanged scalar reference mapper. Three NLQ
tables are generated through the unchanged reference correction API. Runtime
lookup does not approximate coefficients, floor operations, caps or endpoints.
At maximum native depth the mapping tables occupy 6 KiB and the NLQ tables
12 KiB, plus fixed copied configuration/state. Allocation size is bounded and
reported by `yb_cached_sizeof_plan()`; no giant three-dimensional MMR table is
allocated.

Any component containing an MMR segment uses an entire unchanged reference
chunk call. Its mapping, NLQ and stage writes remain reference work; generated
NLQ tables are **unused on that fallback**, and no acceleration is claimed for
it. `yb_cached_component_route()` reports polynomial lookup or batch fallback.
The initial backend deliberately does not duplicate or simplify MMR mathematics.

All three base arrays are required, including the registered luma guide for
chroma. Native codes remain whole integers within their declared 8/10-bit
domain. Lookup output is uint16 mapped data; validated NLQ correction lies in
[-131072,131071], so the signed unrounded sum lies in [-131072,196606] and fits
int32. Final composition uses portable signed-floor arithmetic and the same
rounding bias/output bounds as the reference. This narrower bounded composition
does not change the general scalar API's wider accepted residual type.

## Guards and tracked frames

Chunks contain 1..65536 samples. Complete preflight checks validate pointer
spans, alignment, address overflow, component and all input-code ranges before
any stage write. Four destinations must be mutually disjoint and disjoint from
inputs and the entire owned plan. Input buffers cannot overlap the plan.
Failure leaves all four outputs unchanged; no caller-owned configuration can
become an unchecked mutable cache.

The separate opaque frame wrapper creates a fresh owned session through the
unchanged `yb_integration_init()`, checks frame association, component start and
counts, and advances counts only after successful cached/reference processing.
It uses unchanged `yb_integration_finish()` to require complete 4:2:0 component
counts. Raw/fractional descriptors are rejected; this is not a 4:4:4 Y416 route.
Tokens are caller assertions, not authentication. A failed chunk does not erase
earlier successful chunks, and premature completion leaves the session usable.

Caller-owned buffers must stay accessible, coherent, alive and immutable
throughout a call. The library cannot prove those properties from addresses.
Plans may be read concurrently with disjoint stable buffers, but must not be
destroyed concurrently; frame handles are single-thread-owned mutable sessions.
Destroy only live handles returned by the corresponding create function;
destroy(NULL) is safe. Failed creation leaves the output handle unchanged.

## Build and measure

Link the cached implementation with the unchanged composer, integration and
sampling units; it has no FFmpeg, Kodi or GPU dependency:

```sh
cc -std=c11 -O2 -shared -fPIC -Wall -Wextra -Werror -Wconversion -Wshadow \
  -Iengine/include -Iengine/experimental \
  engine/experimental/native_cached_composer.c \
  engine/src/native_composer.c \
  engine/experimental/native_integration_probe.c \
  engine/experimental/native_sampling_probe.c -o native_cached_composer.so
```

Use a read-only whole-repository/SDK mount, no network, one CPU, a 512 MiB limit
and no extra swap allowance for target compilation. Record actual source/header
and executable identities. Run correctness tests independently before timing.
Compare all four stages against unchanged reference execution and complete
both tracked frame sessions before measuring any speed difference. Include
per-frame table preparation inside measured cached totals, rather than reporting
only steady-state lookup execution. Synthetic correctness or a host build is
not an actual LibreELEC performance measurement; no performance result is
asserted in this contract.
