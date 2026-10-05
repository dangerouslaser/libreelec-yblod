# Direct C arithmetic timing

The integer C stages now have a small benchmark that measures calculation work
without Python pixel conversion or diagnostic file writing inside the timer.
All measured outputs still have to match the independent Python arithmetic.

## Ollie result

2026-10-05, Intel Core i9-14900K, Ubuntu GCC 13.3.0, x86-64 Linux. Five repeats
were measured for each synthetic case. Each repeat processed a fixed buffer of
16,384 component samples 128 times, using one C call from Python for the entire
repeat. Total timed work was 52,428,800 component samples.

| Synthetic case | Minimum | Median | Maximum |
|---|---:|---:|---:|
| Polynomial mapping + enhancement correction | 67.59 | 76.75 | 77.12 |
| MMR order 1 + enhancement correction | 33.89 | 34.95 | 35.09 |
| MMR order 2 + enhancement correction | 28.54 | 30.17 | 30.74 |
| MMR order 3 + enhancement correction | 25.15 | 26.89 | 27.66 |
| Polynomial mapping, enhancement explicitly disabled | 99.81 | 106.08 | 106.91 |

Units are **million component samples per second**, not complete video pixels
or frames per second. This is a single-threaded hot-buffer CPU diagnostic, not
a playback-speed or GPU-throughput claim. Scheduling affinity and turbo state
were not fixed; the process could be scheduled on any of 32 available logical
CPUs. The range across repeats is retained rather than reporting only a best
run.

All four arrays—mapped base, signed correction, unrounded sum and reconstructed
output—matched the Python oracle exactly after every repeat. The C checksum
also matched independently computed expected output. The five workloads use
explicit synthetic inputs and metadata; no film or SK4 data was involved.

The public report is
[native-kernel-benchmark-ollie-20261005a.json](results/native-kernel-benchmark-ollie-20261005a.json).
It pins the compiler command, source/library/build-record hashes, synthetic
input and expected-stage hashes, all 25 timing observations and runtime details.
The composer source used was
`29d8eb549bf00a752ec3d28c99b9a16ce8a256faceec91411b89a46fc3612369`,
including the separately tested signed-floor optimization.

## What the timer includes

`native_kernel_bench.c` calls the actual public `yb_process_chunk` API on every
iteration. Thus the timer includes its metadata/input validation, mapping,
enhancement correction where enabled, composition and writes to caller-owned
buffers. No LTO is used: the composer is a separate translation unit, not a
benchmark-specific replacement or an inlined constant answer.

Each repeat has one untimed warm-up. Input allocation, Python metadata encoding,
Python oracle calculation, final C checksum and Python output comparisons are
outside the timer. The same buffers are deliberately reused and normally hot
in cache. Both monotonic elapsed time and process CPU time are recorded.
The elapsed interval also encloses the two CPU-clock reads; this is not a
cycle-precise timer. CPU time belongs to the process, not an individual thread;
the current driver uses one worker and the kernel starts no extra threads.

This does not measure decoding, hardware scaling, chroma preparation, colour
conversion, input/output transfers, texture access, HDMI packing or presentation.
It does not demonstrate an entire CPU playback pipeline, choose a GPU backend,
or resolve the fractional hardware-EL input contract. The C implementation can
be optimized or integrated independently while Python remains its test oracle.

## LibreELEC VM result

The same unchanged library was then tested on the actual LibreELEC VM: Intel
Core i5-1135G7, four available VM logical CPUs, Python 3.14.8 and glibc 2.44.
Before copying the small diagnostic, its declared dependency was checked: only
`libc.so.6`, requiring symbol versions no newer than GLIBC 2.17. The library
remains an Ollie/GCC 13.3.0 build; the VM's Python compiler version does not
describe the benchmark C compiler.

The same five cases, buffer sizes and five repeats completed successfully.
Every final stage matched the independent Python arithmetic on the VM. Build
record, library identity, synthetic input hashes, expected-stage hashes and
repeat checksums matched the Ollie report exactly.

| Synthetic case | Minimum | Median | Maximum |
|---|---:|---:|---:|
| Polynomial + enhancement correction | 34.50 | 35.72 | 36.55 |
| MMR order 1 + enhancement correction | 17.43 | 18.26 | 18.44 |
| MMR order 2 + enhancement correction | 14.73 | 15.28 | 15.49 |
| MMR order 3 + enhancement correction | 12.54 | 13.52 | 14.02 |
| Polynomial, enhancement disabled | 48.35 | 49.36 | 49.85 |

Again these are million **component samples per second**, with fixed cached
buffers—not frames per second. The VM/host and scheduler were not isolated or
frequency-controlled. GPU offload and end-to-end playback costs remain separate.

Public evidence:
[native-kernel-benchmark-libreelec-20261005a.json](results/native-kernel-benchmark-libreelec-20261005a.json).
The enforced 512 MiB/no-job-swap scope peaked at 23,805,952 charged bytes;
process peak RSS was 33,976 KiB. Memory-limit pressure, OOM/OOM-kill and swap
were zero. Total timed C loops took 2.556 seconds; this excludes the listed
setup, oracle and reporting work.

Only a fresh `/storage/yblod-native-kernel-bench-20261005a` diagnostic directory
was added, occupying 180 KiB after Python cache creation. No existing files
were removed, no settings changed, and no display/GPU jobs were submitted.
Kodi remained active afterwards; available VM memory was approximately 2.79 GiB
and free `/storage` space remained 2,910 MiB.

## Bounds and memory

The driver accepts 1..65,536 samples, 1..4,096 iterations and 1..20 repeats,
subject to a hard aggregate ceiling of 100 million timed component samples.
Each C invocation also has its own iteration/sample-work bounds. Buffers are
allocated once per case, not per iteration. Only a small JSON report is written.
The benchmark-only entry point assumes valid, live caller allocations, with a
separate writable measurement structure that does not overlap inputs or outputs.
It is not a hardened general-purpose pointer-validation API; the Python driver
supplies these private allocations and retains them through the call.

Before the Ollie run there was approximately 14.1 GiB available RAM. Build,
focused tests and measurement used separate 512 MiB/no-job-swap scopes. The
measurement scope peaked at 20,103,168 charged bytes; process peak RSS was
28,760 KiB. These are different accounting measures, including different shared
memory charges. Memory-limit pressure, OOM/OOM-kill counters and job swap were
zero. The host's pre-existing swap use is not evidence of swap by this job.

Six focused tests passed on both the local host and Ollie, including every case,
all-stage oracle checks, one FFI call per repeat, invalid work bounds, required
cgroup enforcement, build provenance rejection and C failure-output guards.

## Reproduce

From the repository root, with fresh paths:

```sh
systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 tools/yblod/reference/native_kernel_bench.py build \
  target/native-kernel-build-NEW

systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 tools/yblod/reference/native_kernel_bench.py run \
  target/native-kernel-build-NEW/libnative_kernel_bench.so \
  target/native-kernel-benchmark-NEW.json \
  --count 16384 --iterations 128 --repeats 5 --require-memory-cap

python3 -m unittest discover -s tools/yblod/reference \
  -p test_native_kernel_bench.py
```

On LibreELEC use the same `run` arguments with the verified copied build and
source files, and `systemd-run --scope` without `--user`. The run's internal
`--require-memory-cap` guard verifies the actual cgroup limit and disabled job
swap before timing; capability inventory alone is not treated as enforcement.

No playback defaults, output settings or existing files were changed or removed.
