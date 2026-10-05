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

## Proposed opt-in strategy—not yet integrated or exercised

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
No executed runner source was changed; the helper has not been used on the VM
or archive.

The Linux advice is nonbinding; it does not prove eviction or establish a
memory bound. Dirty pages should be synced first, and partial-page requests
may not be discarded. See the primary Linux
[file-advice documentation](https://man7.org/linux/man-pages/man2/posix_fadvise.2.html).
The per-file [sync operation](https://man7.org/linux/man-pages/man2/fsync.2.html)
also does not guarantee durability of a newly created parent directory entry.
The helper reports successful advice submission, never a claimed amount freed.

Future small CPU-only validation should record this job's `memory.stat`
(`anon`, `file`, `shmem`, `file_dirty`, `file_writeback`, `inactive_file`,
`active_file`), current/peak/swap and events before and after write, hash,
analysis and advice. Measure that before approving another large GPU cohort.
If advice fails to produce adequate headroom, further bound the live output
footprint; do not simply raise the cap or treat Python RSS as total memory.
