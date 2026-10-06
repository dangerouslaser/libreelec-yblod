# Runtime-uniform libplacebo reuse — measured checkpoint

The isolated hybrid now uses actual libplacebo BL reshaping with float metadata
decoded once per component on the CPU and uploaded through cached GL uniforms.
Integer sampling, NLQ, final quantization, fences and the installed Kodi route
remain unchanged. This is not a complete libplacebo renderer.

## Repeated 4K performance

Eight untimed warmups follow full-output validation, then twelve resident
submit/finish samples are recorded per job. All samples, including slower
exploratory results, are retained in the JSON. Execution order A1,B1,B2,A2.

| Longer test | Integer (ms median) | Hybrid, matched output limits (ms median) |
| --- | ---: | ---: |
| First pair | 16.801 | 8.967 |
| Reverse pair | 16.833 | 8.945 |
| Pooled24 samples per side | 16.833 | 8.951 |

Pooled median reconstruction time is46.83% lower. Candidate samples span
8.766–9.144ms; baseline16.634–17.019ms. This is stable evidence for this resident
frame/workload, not full playback throughput or an exclusive GPU kernel timer.
CPU uniform preparation/upload is inside submit timing. Shader generation,
compilation, decode, per-new-frame preparation/scaling, inherited colour conversion
and output/display remain excluded. Topology changes still require shader
regeneration; numerical coefficients do not.

The preceding shorter ABBA was noisy: first candidate median25.405ms, second
9.321ms, versus16.847/17.001ms native. Its pooled median was12.408ms. It was not
discarded or promoted as a stable result. A per-pixel metadata-conversion
prototype was slower still (23.239ms); the new uniform design addresses that cost.

## Output-limit isolation and accuracy

The initial adapter retained upstream mapped-output pivot limits, but supplied
samples/pivots in our code/1024 input domain. Its maximum mapped output was
therefore1023/1024, below native65535/65536. A separate explicitly labelled
`--uniforms-native-output-range` control sets output-bound uniforms to0/1;
the unchanged native outer Q16 floor/clamp still limits the integer mapped output
to0..65535. Actual libplacebo-generated calculation bodies are not rewritten.
This customized adapter is not default libplacebo's complete playback output.

On the private 4K frame, matched limits remove every difference greater than one
output code. Luma is exact. Of2,073,600 values per chroma plane,6,176 Cb and3,737 Cr
values differ byone; 99.9203% ofall12,441,600 reconstructed values are exact.
Mean signed differences are+0.001326 Cb /−0.00005064 Cr output codes.
All four longer jobs reproduce these counts. Without matched limits, the uniform
candidate still has110,498 Cb differences aboveone and max3. The control thus
demonstrates the output-limit mismatch, not merely a speculation about FP32.

Fourteen public cases (the original12 plus precision base/alternate) compare
86,016 candidate values to the integer oracle. Onlythree total values differ,
each byone code. A single generated shader accepts base and alternate coefficient
sets with identical topology; input layers are identical. These separate-process
cases are supplemented by a same-handle A→B→A test: all6,144 B values change,
restored A haszero mismatches against initial A, and all18,432 frame outputs are
compared to their corresponding CPU references. Each A hasone Cr difference
ofone from the integer model; B is exact. Thus restoration is exact to the
initial candidate, not a false claim of integer-reference identity.

These cases do not prove every metadata combination is withinone code. Neither
integer-model agreement nor these timings establishes SK4/Dolby reference accuracy.
The precision fixture targets halfway values, signed cancellation, low coefficient
bits and small residual corrections, but no per-stage transition histogram has
yet measured comprehensive coverage.

## Resource and publication gates

All jobs were sequential and bounded to512MiB/no additional swap/one CPU/60s.
The longer4K runs hadzero memory-limit/OOM events, zero swap andzero CPU quota
throttling. Final scope memory peaks were about233–237MiB. Software hashes and
Kodi service start identity stayed unchanged. SDK strict warning builds use the
same512MiB/no-extra-swap cap. Private layers, instruction payloads, generated
private shaders and media hashes are excluded from publication.

The topology manifest parser now uses bounded decimal parsing, including rejection
of oversized/missing/extra/signed tokens. Host tests compile and execute the actual
C parser. Five earlier source-layout checks, assembler tests, sequence source
guards and bounded timing-config guards supplement independent reviews; they do
not replace GPU evidence. The sequence's initial strict build caught a shadowed
local variable; it was renamed and the final strict build passed.

## Reproduction

`build_libplacebo_diagnostics.sh NEW_OUTPUT_DIRECTORY` builds all six diagnostics
from published sources inside the SDK. Run it in a512MiB/no-extra-swap/one-CPU
container with the SDK at `/build` and repository at `/repo`; output must be new.

Build the generator against the pinned SDK libplacebo7.372.0
(`e2972fdd09adacd383656738d7d280f0cd84a761` plus repository patches), and the
metadata exporter as documented in the prototype notes. Build the comparison
probe with canonical backend for A, or the isolated
`native_gpu_composer_backend_libplacebo.c` for B, plus the same guard, surface,
frame-bridge, MMR, integration, sampling and native-composer sources; link
`-lEGL -lm`. Use strictC11/-O2/-fno-lto/-Wall/-Wextra/-Werror/-Wconversion/-Wshadow.

Generate with `--uniforms` or `--uniforms-native-output-range`, splice into a new
canonical-template shader and use the published bounded wrapper with pinned
binary/shader hashes. Set `YB_COMPARE_WARMUPS=8` and `YB_COMPARE_SAMPLES=12` via
the systemd scope; accepted values are1..32. Read every output before timings.
The sequence runner additionally takes `--alternate-instructions PATH`; verify
that all five input-plane files are identical between fixtures and their
instruction blobs differ before running it. Generated instruction blobs are
same-build ABI artifacts, not a portable interchange format.

## Remaining before playback adoption

More real frames/metadata and topology changes; explicit cache/rebuild/fallback
handling; independently reviewed selectable Kodi integration; then equal-workload
1917 playback timing/drop/skip and shutdown/lifetime testing. Existing independent
integer reconstruction remains the reference and fallback.
