# Conservative GPU integer-width guard

`native_gpu_guard.c/.h` is an isolated host-side suitability check, not a GPU
backend. It fully validates the unchanged CPU mapper configuration before
checking every used MMR segment. Invalid metadata leaves the report unchanged.
A valid configuration may be rejected by this narrower guard while remaining
fully supported by the signed-128-bit CPU implementation. No silent fallback,
shader dispatch, GPU capability claim or production behavior change occurs.

For each MMR segment let `B = abs(constant) + sum(abs(active coefficients))`.
Require `B <= floor(INT64_MAX / 2^20) = 2^43 - 1`. The report gives the largest
B, total MMR segment count and first rejected component/segment in traversal
order; absent rejection those indices are −1. A polynomial-only configuration
has B0, count0 and supported1. “Supported” means only this arithmetic-width
condition, not that a device or driver implements the required instructions.

All validated 8/10-bit codes, after each channel's own endpoint clamp, are
nonnegative and below `2^b`. Every first-order fixed-point feature is below
`2^20`; the squared and cubed features preserve that bound after their exact
intermediate floors. Feature-generation multiplication intermediates are below
`2^40`, provided operands are promoted to 64 bits **before** multiplication.
Thus each coefficient product and every accumulation prefix has magnitude at
most `2^20*B <= INT64_MAX`, including the constant's `2^20` multiplier.
The sum uses checked unsigned-64 arithmetic; accepted CPU metadata bounds
already imply `B <= 22*2^48 < 2^53`.

This is deliberately conservative. The features are strictly below `2^20`,
and coefficients can cancel, so failing the guard does not prove any actual
sample overflows. No coefficient is truncated or refitted to make it pass.

Validated polynomial mappings always fit signed64: at most three terms, each
bounded by `2^(D+6)*2^20`, yield magnitude at most `3*2^58 < 2^60` for D≤32.
Their integer powers and nonnegative scaling shifts fit as well. Validated NLQ
has pre-limit accumulator magnitude below `2^(D+12) <= 2^44` for b8/10. Its
metadata limit, exact negative floor and final signed composition fit64 too.
This composition claim concerns validated NLQ output—not arbitrary int64
residuals accepted by the wider standalone CPU composition API.

A future independent shader must still preserve right-owned pivots, all
channel clamps, each MMR intermediate floor, negative division semantics,
metadata limiting before NLQ flooring, and the single final round/clip. This
guard does not resolve enhancement-layer fractional transport or scaling.

Build with `native_composer.c` and run
`python3 -m unittest test_native_gpu_guard`. Tests compare arbitrary-precision
Python bounds, threshold-adjacent metadata, signed extreme coefficients, every
accumulation prefix and CPU acceptance of GPU-width rejection. The guard stays
outside the production CMake target until a backend is independently validated.
