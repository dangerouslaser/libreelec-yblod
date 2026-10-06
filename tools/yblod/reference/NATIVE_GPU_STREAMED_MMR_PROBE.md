# Scalar-streamed MMR candidate

This isolated shader removes the dynamically indexed 21-element feature array
and three-element code array from the integer diagnostic. It computes each MMR
feature, its separately floored square, and its separately floored cube product,
then accumulates that feature's coefficients immediately. All arithmetic remains
integer; there is no fitted correction or floating-point approximation.

Accumulation is now feature-major rather than order-major. The existing signed
width eligibility guard bounds the absolute constant/coefficient sum and each
feature is below 2^20, protecting every intermediate prefix under either order.
The shader does not loosen the guard. Polynomial, NLQ and output-stage rules
remain unchanged. The original shader is preserved as a fallback/comparison.

## Measured synthetic checkpoint

All 32 independent CPU fixture gates finished before GPU execution. The 31
eligible fixtures then matched all 8,512 stage values / 2,128 positions exactly.
One valid width-unsupported fixture was rejected without GPU dispatch.

The compiler selected SIMD16 with 1,909 instructions, 128 GRF registers and
zero reported scratch spill/fill instructions. The original generic shader
selected SIMD8 with 1,582 instructions and 42/14 reported scratch spill/fill
instructions; its SIMD16 register allocation failed. The candidate still
reported SIMD32 inefficient. This is a useful structural improvement, not a
measured speedup: different SIMD widths make raw instruction counts incomparable
as per-frame costs. Compiler estimated cycles are not elapsed device timings.

Reported spill/fill counters include source-level scratch accesses as well as
register allocator spills/fills. Zero means zero in these compiled counters,
not a guarantee of all forms of memory traffic being absent.

The job used 65,925,120 peak charged bytes under 512 MiB; job swap and memory
events were zero. Kodi process/start identity and pinned Mesa runtime files
were unchanged. Only the first public MMR3 GPU fixture enabled child-local
compiler debug; the other 30 fixtures ran normally. No clocks, Kodi settings,
shared-cache deletion, or forced SIMD policies were involved.

Public artifacts:

- [Exact synthetic corpus report](results/native-gpu-streamed-mmr-synthetic-20261005a.json)
- [Raw compiler IR/assembly](results/native-gpu-streamed-mmr-compiler-20261005a.log)
- [Parsed static statistics](results/native-gpu-streamed-mmr-compiler-stats-20261005a.json)
- [Original compiled shader checkpoint](NATIVE_GPU_SHADER_INSPECTION.md)

Candidate SHA256:
`5c58ab7ae0f7220a360026153f4d4e5d0592bf00c9d660ce570cb553f531b64a`.
Compiled shader blake3:
`a1cf5d09d5266f091492d273b14beb5b8252fabd359c5a0eeec506c0c00c8c64`.

`native_gpu_streamed_mmr_run.py` is an explicit opt-in runner requiring the
reviewed candidate and original SDK executable hashes. It preserves the original
runner's baseline shader gate. It validates the fixed 32-case public corpus,
rejects changed eligibility/counts, checks source/artifact identities around
each invocation, and limits each child to 30 seconds. Invoke it only inside an
external 512 MiB / no-swap resource scope and coordinate GPU access first.

## Prepared-frame ABBA comparison

[Public scalar evidence](results/native-gpu-streamed-mmr-frame-comparison-20261005a.json)
contains eight cohorts: baseline, streamed, streamed, baseline separately for
each of the two prepared frames. The same pinned single-wait executable and
unchanged private input files were used for both shaders. Separate CPU full-frame
preflights completed before any GPU work. Every cohort then checked all
49,766,400 stage values using 48 GPU batches / 191 CPU oracle subchunks exactly.

| Frame | Baseline pooled median | Streamed pooled median | Lower diagnostic wall time |
|---|---|---|---|
| 2296 | 637.122 ms | 401.066 ms | 37.05% |
| 1406 | 615.636 ms | 355.323 ms | 42.28% |

Each median pools six warm passes across two cohorts. All six streamed whole-pass
times were below all six baseline times on each frame in this run. This supports
a useful improvement for this diagnostic workload, not a sustained/general
playback throughput guarantee: only two prepared frames, no controlled clocks,
and short non-randomized ABBA cohorts. The candidate is still not real-time here.

The untimed full equality gate is distinct from warm timing: warm passes check
only the final 41,984-sample CPU-subchunk suffix (one 671,744-byte readback), not
every output anew. Both paths retain CPU extraction/packing, 48 uploads and
completion waits. Dispatch host intervals may include pending uploads and are
not exclusive device-kernel time. Cold setup/teardown are reported separately.
The 512 MiB/no-swap scope peaked at 122,933,248 bytes, with zero memory events and
unchanged Kodi process identity. Private media hashes, metadata and pixels are
omitted from public artifacts.

Next is actual GPU texture sample ingestion without CPU-expanded sample SSBOs,
preserving declared chroma/guide preparation. These results do not establish
fractional Y416 support, complete metadata coverage, Dolby conformance, actual
movie playback speed or Kodi integration.
