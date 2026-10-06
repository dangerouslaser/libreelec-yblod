# Tiny synthetic enhancement-layer scaling gate

`engine/experimental/native_gpu_el_scaling_runner.c` measures the existing
`native_gpu_el_scaling_probe.comp` literal Annex-B example implementation.
It is not a claim that this filter is required for every Dolby stream/player.

Ten bounded fixtures cover single-component Y and two-component UV: constant,
ramp, low-amplitude impulse, full-range step, and full-range impulse. The
source is 4×4 P010 storage words. The vertical intermediate is 4×8 integer
native-code storage; the final 8×8 plane uses normalized R16/RG16 texture
storage with P010 words. All 480 intermediate and 960 final words are
serialized, alongside expected/observed status. No film input or colour
conversion is involved.

The CPU oracle uses signed floor after the declared integer rounding offset,
edge replication and the literal coefficient arrays. Intermediate limits are
0–65535, not an invented 10-bit clamp. If a final pixel component exceeds
1023, the shader must report status bit4 and leave the whole pixel at the
65535 sentinel. That unsupported overshoot is visible rather than concealed.
The independent Python oracle tests constants, word units, an overshoot
case, and every actual compiled CPU-oracle array.

`--cpu-oracle` performs no device access. A GPU measurement requires explicit
render-node identity, desktop GL4.3, the pinned shader, finite GPU fences and
full cleanup. Run only in a root-coordinated 512 MiB/no-swap scope with a
30-second outer deadline and Kodi/runtime identities verified before/after.
Successful tiny fixtures do not establish full-frame performance, exactness
for every input, playback readiness, or hardware fixed-function equivalence.

Set `YBLOD_GPU_EL_SCALING_RUNNER_BINARY` to the strict SDK-built executable
for the full host suite. Saved evidence is
`results/native-gpu-el-scaling-synthetic-20261005o.json`: all 1440 words and
10 statuses matched independent/native oracles on Intel TGL. Y/UV step cases
explicitly rejected overshoot. Exit status alone is not sufficient evidence.
