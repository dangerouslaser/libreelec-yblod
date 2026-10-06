# Tiny GPU guide/phase execution gate

The standalone runner reuses the reviewed colour runner's exact-device EGL
lifecycle. Eleven explicit synthetic cases compare guide and selected chroma
phase recipes against signed-integer CPU formulas. These are declared recipes,
not inferred universal Dolby/player rules. No decoder, film or playback occurs.

Guide input is 8×8 P010 Q6 words; output 4×4 R16 stores **native codes** (not Q6).
Phase input/output is 4×4 interleaved RG16 P010 Q6 words. Left and top-left choices
are explicit, with separate linear/cubic128 phase operations; cubic negative
floor arithmetic and below/above clip counters remain visible. Edge access is
clamped exactly as the shader declares. Fixtures include ramp, impulse and
checker patterns. Every expected and actual public synthetic storage word and
status is emitted, not only maxima. This gate does not test enhancement scaling.

CLI: `native_gpu_preparation_runner DEVICE SHADER`; `--cpu-oracle` executes no GPU
and exposes the fixture for independent Python checks. Set
`YBLOD_GPU_PREPARATION_RUNNER_BINARY` for those host/compiled CLI tests. Actual GPU
must separately show zero word/status mismatches under a bounded caller scope.
The producer fence waits at most 5×1 second, and the caller must impose an overall
timeout. No tiny-texture result implies full-frame timing or production readiness.

Saved evidence: `results/native-gpu-preparation-synthetic-20261005n.json`.
All 304 words and 33 status fields matched native/independent oracles on Intel
TGL. Cubic fixtures recorded 8 below-range and 4 above-range phase clips.
