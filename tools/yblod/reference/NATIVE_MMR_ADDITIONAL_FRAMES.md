# Additional real-frame arithmetic coverage

The [completed frame 1406 result](results/native-mmr-frame1406-vm-20261005a.json)
extends the term-clearing candidate beyond the original frame 2296 fixture.
It uses frame-specific native decoder instructions, saved prepared BL planes
and guide, and saved software-linear enhancement planes packed exactly to P010.
No GPU, TV, capture or Kodi playback settings changed.

The report's source hashes are a current public-engine source snapshot, not a
complete producer/packer executed-build inventory. Those executables came from
the earlier SDK builds; their separately recorded executable hashes identify
the actual artifacts used. No complete producer-header inventory is claimed.

## Input and metadata gates

The native producer decoded 32 frames/packets to local presentation index 31.
Its successful record confirms decoder metadata, exact raw RPU and all three
active enhancement-plane identities, CRC requested, zero warning/error logs,
ABI 1 and 9216-byte instructions. Instructions were independently generated for
this frame, never copied from 2296. Local raw-window index does not prove the
original stream timestamp; original PTS verification remains false.

The prepared extraction's independently checked narrow parser/EOF relations
were handled with existing fixture-derivation helpers. Original inputs were
retained. No guessed packet positions, relaxed pixel/metadata gates or producer
size-limit changes were introduced. A staging transfer failed before native
execution and was retried via the Mac-authenticated route. The first actual
producer execution succeeded.

The existing native P010 packer accepts only whole native10 codes, shifts them
by six and interleaves chroma without scaling, rounding or clipping. Its fresh
3840x2160 output was exactly 24,883,200 bytes. The enhancement scaling was
already software-linear in this saved fixture: this is **not** an Intel
hardware-scaling or fractional-enhancement validation result.

## Completed reconstruction

Every value in all four stages across all three components matched the unchanged
reference before timing: 49,766,400 stage values, 191 dispatches and completed
counts [8,294,400, 2,073,600, 2,073,600]. Luma used the polynomial lookup route;
both colour segments used proved 64-bit MMR accumulation.

Candidate wall times were 208.982, 206.892 and 205.910 ms, versus paired unchanged
reference 552.460, 530.715 and 530.553 ms. Preparation and teardown are included;
loading/shared scratch allocation, enhancement scaling, decoding, colour
conversion and display are excluded. Timed checks cover the final chunk only;
full-frame equivalence preceded timing. This frame did not pair candidate with
the earlier optimized backend: it establishes broader exact arithmetic coverage,
not another controlled old-versus-new speedup.

The producer/packer scope's retained pre-exit peak was 44,900,352 bytes; the
separate benchmark scope's was 57,253,888 bytes. Both enforced 512 MiB/no swap,
with zero high/max/OOM/OOM-kill events and Kodi active before/after. Inputs,
executables, wrapper and runtime identities were checked before/after each
workflow. Snapshots are not final lifetime peak or GPU memory. Benchmark CPU
quota information was unavailable.

This is reference-equivalent whole-code reconstruction, not independent DV
conformance, closer SK4 output, display adaptation or real-time playback.
Pixels, complete instructions, input hashes and private paths stay private.
The public audit replays the record, not a fresh decoder or benchmark. Further
saved frames need their own metadata and association gates before they count.
