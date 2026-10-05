# Exact prepared colour reconstruction

This separate experimental C backend preserves the reference and the earlier
cached implementation. It does not change Kodi playback, fractional enhancement
processing, colour conversion, TV limits or the default standalone CMake build.

## What changes

Polynomial components retain exact per-code mapping tables. Enhancement
correction uses exact tables for all components, including MMR colour components.
MMR segments prepare sparse coefficient lists once per frame, omit coefficients
that are exactly zero, and calculate only the highest power actually needed.
There is no approximation or reordering of floor operations.

The nonnegative normalized terms are bounded by 2^20. Their intermediate
products are bounded by 2^40 and fit unsigned 64-bit arithmetic. For whole
8/10-bit codes, squaring a normalized component and shifting by 20 is exactly
the original component-square formula: both grids divide without a remainder.
Cross-products and subsequent square/cube floors retain their original order.

For each MMR segment, preparation calculates this conservative bound in
unsigned 128-bit arithmetic:

```text
bound = 2^20 * (abs(constant) + sum(abs(active coefficients)))
```

Only if this bound is at most INT64_MAX are signed 64-bit products and sums
used. Every product and every partial sum is then representable, including
negative coefficients and cancellation. Other segments retain signed 128-bit
accumulation. Width is selected from metadata, never observed pixels or display
specifications. This is a performance choice, not a new correction limit.

Final signed-floor arithmetic, mapped-value bounds, unrounded signed sums and
10/12-bit reconstruction rounding match the unchanged reference. Mixed
polynomial/MMR components retain original-code pivot selection and per-channel
endpoint clamping. No giant three-dimensional lookup table is allocated.

## API and safety

`native_mmr_composer.h` exposes opaque owned plan/frame handles with version and
size queries. Configuration is copied; changing caller metadata requires a new
plan. All chunk input codes, alignment, span/address overflow and aliases are
checked before any of the four outputs are written. Count is 1..65536.
Disabled enhancement requires NULL NLQ and enhancement pointers. Failed calls
leave outputs and frame counts unchanged. Frame association, sequential counts
and completion retain the established integration contract. Tokens are caller
assertions, not authentication; buffers must remain accessible and coherent.

Component route 1 means polynomial lookup; 0 means prepared MMR, not the old
reference fallback. Segment queries return 64/128, 0 for polynomial, or -1 for
invalid arguments. Frames are single-thread-owned; immutable plans may be read
concurrently only with stable, disjoint outputs and no concurrent destruction.

## Build and test

From the repository root:

```sh
cc -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -Wconversion -Wshadow \
  -fno-fast-math -ffp-contract=off -Iengine/include -Iengine/experimental \
  engine/experimental/native_scaled_frame_mmr_benchmark.c \
  engine/experimental/native_mmr_composer.c \
  engine/experimental/native_scaled_surface.c \
  engine/experimental/native_decoder_frame_bridge.c \
  engine/experimental/native_integration_probe.c \
  engine/experimental/native_sampling_probe.c \
  engine/src/native_composer.c -o native_scaled_frame_mmr_benchmark
python3 -m unittest discover -s tools/yblod/reference -p 'test_native*mmr*.py'
```

The synthetic tests compare all four stages with unchanged C and independent
Python equations, including all orders, sparse/zero terms, maximum accepted
coefficients, negative cancellation, accumulator-width boundaries, disabled
enhancement and atomic rejection. Normal and undefined-behaviour builds are
checked separately. No movie or licensed player is needed for these tests.

The benchmark uses the same private prepared input contract as the earlier
paired benchmark. Its full untimed frame equivalence gate precedes one warmup
and three alternating-order pairs. Preparation, extraction, four stage writes,
completion and teardown are included; input loading, shared scratch allocation,
GPU scaling, decoding, colour conversion and display are excluded. Timed output
crosschecks cover the final chunk only, not every timed frame value. Separate
translation units and no LTO preserve observable external processing calls.

## Completed VM checkpoint (2026-10-05)

The [public report](results/native-mmr-frame-vm-20261005a.json) records the
completed 3840x2160 whole-code test. All 49,766,400 stage values across 191
dispatches matched byte-for-byte before timing, and both sessions completed
[8,294,400, 2,073,600, 2,073,600] component counts. Both MMR segments selected
proved 64-bit accumulation; wide accumulation remains covered by synthetic
maximum-coefficient, cancellation and bound-transition tests.

Reference wall times were 603.930, 607.884 and 604.654 ms. Optimized times were
263.588, 257.994 and 258.599 ms. Median time fell from 604.654 to 258.599 ms,
about 57% less time, including 0.639–0.712 ms of preparation and full teardown.
The earlier luma-only cached median was 404.596 ms in a separate cohort;
that historical comparison is not a paired old-cache/new-MMR measurement.

The retained pre-exit cgroup peak snapshot was 57,659,392 bytes (about 55 MiB),
under a 512 MiB/zero-swap cap, with zero high/limit/OOM/OOM-kill events. This
is not final lifetime peak, process RSS or GPU memory. CPU quota information
was unavailable in the runtime scope. Source/header inventories matched before
and after SDK compilation; executable, private inputs, wrapper and libc/loader
identities matched before and after runtime. Kodi remained active.

An initial launch command with unsupported scope flags was rejected before C
execution. The completed cohort used a fresh direct scope. No GPU, decoding,
display, movie capture or production playback settings were changed.

This is still an offline diagnostic, not playback FPS or independent real-frame
DV conformance. It does not show closer SK4 output or establish fractional Y416
rules. Private pixels, instruction blobs, input hashes and paths stay excluded.
