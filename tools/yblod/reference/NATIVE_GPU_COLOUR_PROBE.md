# Experimental float GPU colour stage

This standalone GLSL4.3 compute shader translates the native double colour
stage into float arithmetic. It is **not bit-exact**, not a Dolby conformance
claim, and must not be adopted on the strength of host source tests alone.
It implements source matrix/offset, PQ decoding, source LMS, explicit caller
target inverse LMS, PQ encoding, inverse target YCC/offset and existing bounded
12-bit quantization. There is no display adaptation, SK4 fitting or target default.

The caller validates a native configuration first, converts it to finite float
uniforms without concealing overflow, and supplies CPU-computed target inverses.
Native matrices are row-major; GLSL matrices are indexed `[column][row]`.
Upload explicit column-major packed values with transpose=false, or use the
desktop GL transpose flag consistently. No sampler/chroma expansion is done.
Inputs are std430 vec4 reconstructed/expanded12-bit codes; padding is unused.
Outputs are four vec4 stage boundaries followed by uvec4(status,code0,code1,code2),
80 bytes per sample. Failure records contain zero stages/codes plus status.

Status0 means arithmetic completed,2 invalid float config,3
PQ/nonfinite arithmetic domain failure. Native caller atomic whole-chunk semantics
are not implied by per-sample shader status. Nonfinite/outside inputs are domain errors.
PQpolicy0 rejects outside[0,1]; policy1 clamps negative PQ arguments to zero and
allows finite positive extension only while the PQ decode denominator is positive.
No float epsilon clamping or special near-boundary correction is introduced.

Before production use an actual GPU runner must compare against native C double
at **every emitted stage**, record max absolute/relative errors, all status
mismatches and quantized-code differences, and apply explicitly chosen tolerances.
Near-domain/rounding boundaries need separate fixtures because float rounding can
change acceptance or final codes; failures must remain visible. Thresholds must
come from an explicit engineering budget, not SK4 resemblance. Full-range and
real-media measurements remain required. `precise` inhibits unintended contraction
in explicit products/sums but does not make GPU pow match host libm.

`native_gpu_colour_runner DEVICE SHADER` provides the actual execution gate:
six explicit synthetic configurations ×12 samples, with native C oracle computed
before opening a device. It reuses exact-device EGL association and bounded
fences; no movie files or decoder are involved. Configurations pair strict and
extended policies for identity, nontrivial target matrices/offsets and a doubled
source matrix (including domain failures). Samples include endpoints, fractional
codes, out-of-range and nonfinite values. The runner checks every GPU status and
finite output, reports every successful pair's12 stage-value absolute errors,
all code differences and aggregate absolute/relative errors/status mismatches.
Relative error uses max(abs(native),1e-12); input/uniform float conversion errors
are reported separately. It reports `tolerance_selected:false` and
`adoption_pass:null`: measurements are not silently promoted to an accuracy pass.
The runner succeeds when measurement/cleanup finishes, even if arithmetic
differences exist. Caller must inspect the metrics and impose an overall timeout.
Optional compiled guards use `YBLOD_GPU_COLOUR_RUNNER_BINARY`.

## Measured synthetic checkpoint

On Intel TGL/Mesa26.2.4 the actual shader/runner completed72 status comparisons:
34 successful pairs and38 matching domain failures, with **zero status mismatches**.
Two of102 compared code values differed by+1, both the same fractional identity
input under strict/extended policy. Native double round-trip landed below the
half-code boundary while float landed above it. No correction was added to force
agreement. This is why float is not described as bit-exact or adopted silently.

Stage max absolute errors (source nonlinear, common LMS, target linear,
prequantized transport): `[5.72204589266434e-9,0.02795524675764227,
0.02795524675764227,4.518354518889822e-5]`. Max relative errors with the documented
1e-12 floor: `[4.749745128457272e-8,8.900688729764116e-5,
8.900688729764116e-5,2.0709075637429603e-5]`. Large absolute linear errors include
extended-domain synthetic values; neither this small fixture nor these maxima
establish a real-media accuracy budget.

Peak scoped memory was38,461,440bytes; no memory-limit events or job swap. Kodi
process identity and all pinned files/runtime libraries stayed unchanged.
Nine runtimes were pinned (existing eight plus libm for the native CPU oracle).
All individual numeric errors/code differences are public in
`results/native-gpu-colour-synthetic-20261005k.json` with source/binary hashes.
Initial compiler failures exposed the reserved GLSL identifier `common`; the
final shader uses `common_lms`, with no arithmetic changes. No production
playback or actual metadata was tested by this checkpoint.
