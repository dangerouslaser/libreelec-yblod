# Synthetic metadata fragmentation probe

`native_metadata_fragment_probe.c` is a separate CPU-only test of the existing
serializer, leaving the original v1 probe/checkpoint unchanged. It requires the
actual patched `dvbridge_metadata.h`, `mpv_dvbridge_cm4.h`, FFmpeg `dovi_meta.h`
and matching `libavutil`; metadata comes from `av_dovi_metadata_alloc`, not a
locally reproduced ABI. No GPU, Kodi playback, TV, film or real RPU is used.

Each case first commits a 95-byte synthetic baseline, then serializes its target
on a copied state. Only success commits the candidate. Thus the oversized case
must preserve an already populated outer state; this does not claim the inline
serializer itself avoids mutation before rejecting a candidate.

The baseline is 71 fixed bytes, L1 (5-byte extension header +6 data bytes), and
L5 (5+8). Distinct L2 targets add 19 bytes each. Input L5 deliberately precedes
the L2 blocks; level ordering moves it after L2 while preserving descending
same-level target order. Each L2 target is `1000+i`, slope `2048+i`, other trim
words2048, and ms-weight−1 (wire65535), with `i` descending. This is accepted
serializer/converter grammar, not Dolby-conforming metadata or TV trim semantics.

| Case | Target bytes | Expected packets |
| --- | ---: | ---: |
| baseline | 95 | 1 |
| l2-2 | 133 | 2 |
| l2-8 | 247 | 3 |
| l2-15 | 380 | 4 |
| l2-20 | 475 | 4 |
| l2-21-reject | 494 | rejected above482-byte cap |
| boundary-119 | 119 | 1 |
| boundary-120 | 120 | 2 |

Boundary119 adds basic raw L8 (10 source bytes: index1 and six12-bit2048
controls; converted13 bytes plus5-byte header), then L9 index0/raw length1
(1+5). Boundary120 replaces L9 with L254/raw length2 containing two zeros
(2+5). These lengths and rules were inspected in the actual pinned converter,
not inferred from nominal block numbers. The compiler requires allocator-header
capacity of at least23 blocks and the runtime bounds helper checks actual ext
storage before populating any block.

## Independent acceptance tests

`test_native_metadata_fragment_probe.py` reconstructs packets independently:
first packet has119 payload bytes, later packets121; minimal packet count,
first/middle/last tags, duplicate-nibble identity, zero reserved/padding bytes,
declared payload length, CRC-32/MPEG-2 and exact assembly are checked. The CRC
known answer is `123456789 → 0x0376e6e7`. Extensions must exactly exhaust the
payload and match literal L1/L5/L2/L8/L9/L254 words/order. The rejection exposes
no payload/packets and preserves committed counters/state.

Three local parser tests use explicitly invented wire fixtures only,
including CRC-repaired semantic corruptions and capacity boundaries119/120,
240/241,361/362 and482. Three native assertions now replay the actual public
checkpoint by default; this invokes neither C nor any device. If no executable,
archive or public checkpoint is available they explicitly skip. Executable
selection takes precedence, then archive, then the public checkpoint.

The public checkpoint is
`results/native-metadata-fragments-libreelec-20261005a.json`. Default replay
uses a regular-file/no-follow read capped at1MiB+1, descriptor/path stability
checks, duplicate/nonfinite JSON rejection, exact ordered cases/record fields,
strict types, fixed executed C/script/header/library/binary identities and
independent packet validation. Original stdout digests are checked by rebuilding
the fixed compact C JSON grammar from each stored result. Two added regression
tests reject corrupted identities, records, case order/log hashes, oversized or
nonregular reads and symlinks. The final default suite has eight tests with no
skips: three parser, two checkpoint-reader and three native-output assertions.

```sh
YB_NATIVE_METADATA_FRAGMENT_PROBE=/path/to/reviewed/executable \
  python3 -m unittest -v test_native_metadata_fragment_probe
```

Alternatively `YB_NATIVE_METADATA_FRAGMENT_ARCHIVE` points to a retained cohort
directory containing `cases/<case>.json`, `.stderr` and `.exit-status`. This is
replay, not fresh C execution. Root must review/build before any bounded VM CPU
cohort; original serializer/header sources and production defaults are untouched.
Compile with the existing SDK against its actual headers and `-lavutil -lm`.
Record compiler command/version, source/dependency/library/binary hashes before
and after execution. The actual SDK build and VM CPU cohort described below
have completed; no new VM job is needed for replay.

Inspected bridge dependencies:

- `dvbridge_metadata.h`: `da799ab08381318601bb0a3f8a1a74ed3293ca09b2cdde52228ea6f7e4c06d36`
- `mpv_dvbridge_cm4.h`: `f6762808f5d7a5824983d72b0188098f19e86bd2a6db7b997ef63e2d35612661`
- Matching previously pinned SDK `dovi_meta.h` (root verifies for build):
  `f860511cb8be3c992b4ef7da6747d8dc9670d64d276aeab3a7e6867112857a02`

Wire preservation establishes only this local synthetic transport property, not
licensed playback, HDMI interoperability, colour accuracy or a selected EL rule.

## Actual LibreELEC CPU cohort

The reviewed C source compiled with the actual pinned headers/allocator using
GCC16.2.0, C11/O2/Wall/Wextra/Werror, in the root's read-only SDK build with a
512MiB limit, one CPU and no network. Binary SHA256 is
`9f086053df1ac496db1016183ae9c856a75c418cccc18ec0ac47c18992bb651d`.
SDK and installed LibreELEC libavutil SHA256 were identical:
`16e16a2ab0f89a48c7e487d365e84f1c005f119fa8754c146daaeff40883c108`.
No ABI stand-in or replacement runtime library was used.

Eight fixed cases produced16 records:15 successful serializations and one
deliberate over-cap rejection. Five targets exercised multiple packets; exact
119/120 boundaries and 475-byte four-packet payload passed. The 494-byte
candidate rejected without exposing packets or changing seeded outer state.
All six original tests passed against the retained actual logs with no skips.

The fresh CPU-only VM scope imposed512MiB and zero job swap; all recorded
max/OOM/kill events and swap counters were zero. Its last in-script
`memory.peak` snapshot was3,567,616 bytes (about3.40MiB), before subsequent
shell/unit cleanup: not completed-unit lifetime peak, process RSS or device
memory. Kodi remained active; no display/GPU/Kodi setting or playback operation
was performed. Binary/library guards passed before/after the cohort and all
three dependency hashes were reverified after the SDK build. The full archive
remains retained on Ollie; public output contains only synthetic bytes/digests.

`source_sha256` pins the C and shell script actually executed. Separately,
`analysis_sha256` pins these later replay tests/documentation at publication;
they were revised after the cohort, not retroactively executed sources. Replay
is source-pinned historical evidence, not fresh native execution or proof of
Dolby-conforming metadata, TV response, HDMI interoperability or film accuracy.
