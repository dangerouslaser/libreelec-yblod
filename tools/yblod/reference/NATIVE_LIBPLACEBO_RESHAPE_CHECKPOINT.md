# Libplacebo reuse checkpoint — 2026-10-06

Source is public; no Kodi or canonical shader change is adopted. The experiment
uses actual libplacebo-generated FP32 base-layer reshaping, preserving native
sampling, integer NLQ and final quantization. It is not the full libplacebo renderer.

## Accuracy

Twelve public 64x64 cases passed execution/completion/resource gates against both
shaders. All 73,728 candidate reconstructed codes were compared to the integer
CPU oracle. Ten cases were exact; two each changed one Cb value by one code.
No public-case error exceeded one native output code. These are bounded fixtures,
not an exhaustive proof.

On the private 4K frame, brightness remained exact. The constant candidate changed
119,813 Cb values (110,498 by more than one; max3) and 3,845 Cr values (max1).
The runtime candidate changed119,829 Cb /3,688 Cr; its max errors were also3/1.
Every run compared all12,441,600 reconstructed values before warm timing.

The adapter preserves input/pivot normalization at code/1024. Libplacebo's
generated output upper bound is consequently1023/1024, while native mapped
values can reach65535/65536. In the constant result,94,854 changed Cb values
were native output4095 and became4092–4094. That provides concrete evidence for
an output-limit-policy mismatch, rather than attributing the full error to FP32.
Constant versus runtime outputs differed at202 Cb and335 Cr values, all by±1;
do not describe those variants as byte-identical.

## Initial performance — not playback

| 4K candidate | Median resident composer submit/finish (ms) |
| --- | ---: |
| Canonical integer | 16.943 |
| Libplacebo, constant coefficients | 9.802 |
| Libplacebo, per-pixel runtime coefficient initialization | 23.239 |

These are first exploratory pairs, not ABBA-qualified playback improvements.
Constant coefficients allow extra optimization; the runtime adapter includes
expensive per-pixel conversion/initialization. Compilation, changing-frame cache
costs, preparation, scaling, colour and display are excluded. The next candidate
prepares floating metadata once on the CPU and uploads uniforms, followed by
matched-limit and repeated 4K comparisons.

The initial tiny case was0.135ms integer /0.126ms constant. Full public-case
paired samples are in the JSON; those timings are overhead/jitter, not4K scaling.
The initial tiny-case executable predated the distinct comparison schema and is
not used as the finalized matrix binary. Finalized binary SHA:
`4faed27a81e27f8ac5b1a7fa3221022b1543ffd546ee4ab8ab76599c03bc84d4`.

## Safety and evidence

SDK builds and VM jobs:512MiB, no additional swap, one CPU, GPU jobs sequential.
Zero memory-limit/OOM events or swap in every collected run; software and Kodi
service start identity unchanged. Runtime R1 had2 CPU throttling events totaling
328microseconds over its whole scope; do not claim all CPU counters were zero.
4K final scope peaks were approximately259–268MiB. The JSON stores earlier
before-wrapper-exit peak snapshots separately, not final whole-scope peaks.

The patched dependency is libplacebo7.372.0 at upstream
e2972fdd09adacd383656738d7d280f0cd84a761 plus the repository patchset. Its actual
BL reshaping implementation was not modified by those patches. Nine source
contract/assembler tests pass; independent layout/lifetime audits passed.
Film layers, metadata payloads, generated private shaders and media hashes remain
private. Aggregate errors measure difference from our integer model, not Dolby
conformance, SK4 accuracy or visible display differences.
