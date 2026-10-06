# Component metadata-buffer experiment

The candidate removes one potential OpenGL update hazard by assigning separate
metadata buffers to the three component dispatches and uploading all three
before dispatch. Metadata, shader arithmetic, errors, barriers, fences and
borrowed-resource guards are unchanged. Storage increases by 6,704 bytes.
Khronos recommends multiple buffers when updates overlap pending GPU reads:
https://raw.githubusercontent.com/KhronosGroup/OpenGL-Refpages/main/gl4/glBufferSubData.xml

It is **not activated** in the canonical engine: the measured results did not
show a consistent performance improvement.

## Paired result

ABBA order used the same resident 3840×2160 inputs and unchanged shader, with
one warmup and three wall/CPU timing samples per run. All four verified runs
matched all 12,441,600 reconstructed GPU codes across three output planes to
the native CPU oracle. CPU preflight checked 49,766,400 stage values per run.
This is composer-output evidence for one fixture, not whole-pipeline colour
accuracy, unique display cadence or the signed/multipivot synthetic corpus.

| Run | Variant | Warm wall times (ms) |
| --- | --- | --- |
| A1 | Baseline | 32.840, 32.781, 32.650 |
| B1 | Candidate | 32.966, 32.577, 25.113 |
| B2 | Candidate | 47.655, 47.838, 37.656 |
| A2 | Baseline | 32.512, 32.804, 32.669 |

B1 was mixed; B2 was slower in every sample. The cause is not established.
Complete unrounded wall and CPU samples, executable/source/shader pins and
resource evidence are in the companion JSON. Each job had a hard 512 MiB
memory limit, zero additional swap, CPUQuota100%, and a 60-second runtime
limit. Peak memory was below 224 MB; memory events and swap were zero. Binary,
shader and eight runtime-library hashes and Kodi identity stayed unchanged
within each verified job. No Kodi playback/service mutation was performed.

GPU frequency, client engine busy time and CPU throttling counters were not
captured. CPU quota effects on submit/finish wall times are unknown and these
timings must not be presented as unrestricted Kodi playback performance.
Initial wrapper attempts encountered missing timeout/cmp tools; the verified
ABBA reruns used systemd's runtime bound and hash comparisons. Both initial
failures are retained in the JSON, not treated as successful paired samples.

## Reproduction and test scope

Apply `experiments/native-gpu-component-buffers.patch` to an isolated copy of
`engine/experimental/native_gpu_composer_backend.c`. The companion regression
test applies that patch to a temporary copy and checks source structure and
saved results; it does not alter the canonical source or execute a GPU.
Compile baseline and candidate against the same existing
`native_gpu_composer_image_probe.c`, guard, scaled-surface, decoder-frame,
MMR, integration, sampling and native-composer sources, linking EGL and math.
Use the same shader and caller-owned valid fixture files with the existing
runner CLI: node, shader, width, height, instructions, BL-Y, BL-Cb, BL-Cr,
guide and P010 enhancement. Keep files read-only; no media accompanies this
report. Repeat ABBA under controlled conditions with clocks/busyness and CPU
throttling captured before considering adoption.

Strict SDK compilation and 19 executable injected-cleanup checks passed;
the latter exercise partial-ID cleanup, deletion-failure retention/retry and
pending-destroy guards, not full creation/upload fault injection. Five private
source-structure checks also passed. No benefit or universal exactness claim
is made from those tests.

The public cleanup harness is
`engine/experimental/native_gpu_component_buffers_cleanup_probe.c`. To run it,
copy it beside `native_gpu_composer_backend.c` in the isolated patched tree;
its quoted include deliberately consumes that local patched backend. Compile
the harness with the real `native_gpu_guard.c` and `native_composer.c`, engine
experimental/include header paths and desktop GL headers. Use the same strict
C11 compiler flags as the backend. It requires no driver, EGL context or GPU;
every cleanup GL operation is injected. Running this harness against the
unpatched canonical backend is not the candidate test.
