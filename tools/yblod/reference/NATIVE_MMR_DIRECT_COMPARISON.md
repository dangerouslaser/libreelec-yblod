# Direct comparison of exact colour backends

The [completed aggregate report](results/native-mmr-direct-comparison-vm-20261005a.json)
compares the preserved prepared-MMR backend with the newer per-code-decision
tables. Both were rebuilt with the same LibreELEC SDK, strict `-O2` flags,
separate translation units and no LTO. Source and binary hashes are recorded.
The benchmark source itself was unchanged.

## Protocol

Six fresh benchmark process cohorts used the same hash-checked private 4K
whole-code inputs on the same VM, sequentially, never concurrently:

1. Baseline, candidate.
2. Candidate, baseline.
3. Baseline, candidate.

Each cohort retains the original diagnostic: an untimed full-frame four-stage
comparison with the unchanged reference, completion checks, one warmup per
backend and three timed backend/reference pairs. The outer comparison uses
the optimized backend's three-sample median from each process. This is paired
process-cohort evidence, not a new single-process frame-alternating harness.
The reference's work between samples is identical for both implementations.

Preparation and teardown are included. Shared input loading/scratch allocation,
hardware scaling, decoding, colour conversion and display are excluded. Timed
output checks cover only the final chunk; full-frame exactness is checked
before timing in every cohort. Files, executable, wrapper and runtime library
identities were checked before and after every run. Private pixels, instructions,
input hashes and paths are excluded from publication.

## Results

| Pair | Baseline median | Candidate median | Less time |
| --- | ---: | ---: | ---: |
| 1 | 261.099 ms | 245.263 ms | 6.1% |
| 2, reversed order | 267.954 ms | 241.903 ms | 9.7% |
| 3 | 262.873 ms | 239.012 ms | 9.1% |

Across all nine timed samples per optimized path, pooled medians were
262.873 ms and 242.030 ms: about 7.9% less diagnostic processing time.
The candidate won all three pair-median comparisons. This confirms the earlier
historical comparison on this input; it is not statistical significance or
evidence of a uniform speedup across all media and hardware.

All six untimed gates matched 49,766,400 stage values across 191 dispatches
and completed the expected [8,294,400, 2,073,600, 2,073,600] component counts.
Every fresh scope had a 512 MiB/no-swap limit, zero high/max/OOM/OOM-kill events,
zero swap and Kodi active before and after. Retained pre-exit memory peak
snapshots ranged from 57,348,096 to 57,745,408 bytes. These are not lifetime
peaks, process RSS or GPU memory. CPU quota controller data was unavailable.

## Decision and remaining work

Keep the per-code-decision candidate as the preferred experimental CPU path
for subsequent measurements, while retaining the earlier backend and unchanged
reference. This document does not switch Kodi or the default standalone build.
Next validation should cover other real frames and metadata, followed by
reducing shared colour work or moving the heavy calculations to a GPU path
without changing mathematical results. This one whole-code fixture cannot
resolve fractional enhancement rules or establish independent DV conformance.

Build commands are in NATIVE_MMR_COMPOSER.md and NATIVE_MMR_PREPARED_COMPOSER.md.
The public regression test replays and audits this pinned evidence; it does not
run the VM or provide another performance measurement.
