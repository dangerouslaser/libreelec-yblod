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

## Proposed opt-in strategy—not integrated into GPU runners

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
No executed GPU runner source was changed. The helper has now been exercised
only in the separately approved 8 MiB CPU-only experiment below, not on the
retained large-cohort evidence.

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
