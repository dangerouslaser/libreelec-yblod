# Bounded evidence retention for future large diagnostics

The completed production-size near-neutral job reached a kernel cgroup peak
of 505,266,176 bytes (481.86 MiB), versus Python peak RSS of 27,468 KiB. It
retained 302,745,600 bytes of raw files, used sequential GPU jobs and remained
under its 512 MiB limit without job swap or max/OOM events.

Its completed cgroup has since disappeared. The report retained current/peak
memory and events, **not `memory.stat`**, so the peak cannot now be apportioned
between file cache, anonymous memory, children and other charges. File-cache
retention is a plausible contributor, not a measured breakdown.

Source inspection shows that both repeats are created before analysing the
first output; outputs are hashed during invocation collection, rehashed for
repeat comparison, and reread for raw statistics and near-neutral counts.
Bounded Python row arrays therefore do not bound retained kernel file cache.

## Opt-in strategy—defaults unchanged

Keep all evidence files and the existing cap. Process the first output through
its hash, required metadata validation, profiles and statistics before admitting
the next repeat; retain the hash/result for comparison. After a repeat is
verified, request release of only that completed file's cache. Preserve every
same-format identity gate before any scaled job. Inputs can receive the same
advice after each completed consumer, accepting that a later consumer must
read them again. Do not globally clear caches or discard evidence.

`file_cache_release.release_verified_file(path, expected_sha256,
expected_bytes)` is an isolated, opt-in building block. It opens only a regular
nonsymlink file through a read-only descriptor, hashes in 64 KiB chunks,
validates size/content/identity, calls `fsync`, then submits
`POSIX_FADV_DONTNEED` for that file. Writers and readers must already be closed,
and the caller must maintain stable ownership. Concurrent readers of the same
file may experience a performance effect. Unsupported platforms and syscall
errors are explicit failures, not silent fallback. Verification reads are
bounded by the declared byte count plus one, rejecting a growing writer rather
than chasing an indefinitely expanding file. Seven mocked tests cover ordering,
strict validation, changed/growing files, failures and evidence preservation.
Original executed GPU runner versions remain preserved. The neutral runner
now offers explicit `release_cache=True` / `--release-cache`; the default
behavior is unchanged. After the CPU-only check, separately approved fresh
small and production-size opt-in cohorts were measured as described below.
Old retained evidence was not modified or deleted.

The Linux advice is nonbinding; it does not prove eviction or establish a
memory bound. Dirty pages should be synced first, and partial-page requests
may not be discarded. See the primary Linux
[file-advice documentation](https://man7.org/linux/man-pages/man2/posix_fadvise.2.html).
The per-file [sync operation](https://man7.org/linux/man-pages/man2/fsync.2.html)
also does not guarantee durability of a newly created parent directory entry.
The helper reports successful advice submission, never a claimed amount freed.

CPU-only validation records its job's `memory.stat`
(`anon`, `file`, `shmem`, `file_dirty`, `file_writeback`, `inactive_file`,
`active_file`), current/peak/swap and events before and after write, hash,
analysis and advice. Review those observations before another large GPU cohort.
If advice fails to produce adequate headroom, further bound the live output
footprint; do not simply raise the cap or treat Python RSS as total memory.

## One 8 MiB CPU-only observation

The [retained probe report](results/intel-file-cache-probe-8m-v1.json) records one
fresh 8 MiB synthetic file. No GPU job, Kodi/display change, global cache action
or deletion occurred. The helper/probe source hashes matched before and after
execution; the file and both exact sources were archived and hash-verified on
Ollie, with the VM copies preserved.

| Snapshot | Cgroup `file` charge, bytes | `memory.current`, bytes |
| --- | --- | --- |
| Before write | 12,288 | 9,801,728 |
| After write | 8,400,896 | 18,714,624 |
| After hash | 8,400,896 | 18,583,552 |
| Immediately after advice, before rehash | 12,288 | 9,924,608 |
| After verification rehash | 8,400,896 | 18,182,144 |

The observed file charge dropped by exactly **8,388,608 bytes (8 MiB)** after
the verified-file helper, then increased by exactly that amount on rehash.
The immediately-after-advice sample was taken before the rehash could bring
the data back into cache. This is cgroup accounting for this run, not a
guarantee of eviction, a per-page residency check or proof of future large-run
headroom. All file hashes remained exact; persisted evidence was unchanged.

The recorded memory maximum was 536,870,912 bytes, swap maximum/current/peak
were zero, and every max/OOM event was zero. Actual cgroup peak was 18,714,624
bytes (17.85 MiB); process peak RSS was 20,688 KiB. These distinct metrics need
not agree. The CPU-only probe took 0.058 seconds, not a GPU or playback timing.
No further run or GPU-runner integration follows automatically from this result.

## Separately approved GPU equivalence checkpoints

The [small opt-in cohort](results/intel-y416-near-neutral-small-cache-release-v11.json)
completed 24 sequential jobs and 52 successful required advice events. All four
input records, all 24 output hashes and every result—including raw profiles,
word sets, low-bit and near-neutral counts, and repeat hashes—were exactly equal
to the retained small baseline. Its kernel cgroup peak was 44,646,400 bytes
(42.58 MiB); no claim of a controlled small-run memory improvement is made.

Only after that equivalence check, the separately approved
[production-size opt-in cohort](results/intel-y416-near-neutral-large-cache-release-v11.json)
completed eight sequential jobs and 18 successful required advice events.
Both input records, all eight output hashes and every result were exactly equal
to the retained production baseline. All four P010 identity gates completed
before any Y416 scaling. No change to fractional handling, metadata, phase,
image quality or playback policy was introduced.

The opt-in production run recorded a kernel cgroup peak of **271,278,080 bytes
(258.71 MiB)**, versus 505,266,176 bytes (481.86 MiB) in the prior baseline run.
These are two actual offline observations, not a controlled benchmark or a
guaranteed bound. The memory cap remained 536,870,912 bytes, job swap maximum
was zero, and swap/max/OOM events remained zero. Process peak RSS was 28,136
KiB. Runner duration was 11.453 seconds, versus 10.854 seconds previously;
this includes evidence handling and must not be presented as playback timing.

For each of the four 4K Y416 output advice events, sampled `memory.stat.file`
charge fell by exactly **66,355,200 bytes**, the packed output size. At those
post-job snapshots, anonymous charge was approximately 13–15 MiB and shmem was
zero. Child/GPU transient memory still contributes to the job's peak and is
not explained by those post-job samples. Advice remains nonbinding and is not
a physical-page residency test.

Every file remains recoverable: inputs, raw outputs, logs and the exact executed
runner/helper sources were copied to Ollie's ignored archive and hash-verified;
the VM originals remain. Neither cohort changed Kodi, display settings, the
TV/SK4, global caches, or the memory limit. The helper is pinned and opt-in;
an advice failure stops the runner without fallback or deletion.
