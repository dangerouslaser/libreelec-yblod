# Existing tunnel serializer: synthetic host-only checkpoint

`native_metadata_probe.c` exercises the existing `dvbridge_metadata.h` serializer,
not a replacement or new display-mapping algorithm. Nine fixed public synthetic
cases cover baseline, changed L1, added/changed L2, added/changed L8, repeat,
seek/discontinuity, and deliberate duplicate-L1 rejection. No GL, EGL, DRM,
connector, TV, decoder or film data is used.

The caller must compile against the actual patched Kodi bridge headers and
matching FFmpeg `libavutil/dovi_meta.h` and library. Metadata is allocated using
`av_dovi_metadata_alloc`; its ABI is not recreated locally. The header's region
validator runs before the serializer. Actual bridge geometry is full 3840x2160.
Residuals are disabled in these synthetic metadata fixtures; no FEL pairing or
licensed-player correctness is implied.

L8 uses the real converter's accepted 10-byte raw grammar: one byte target
index plus six 12-bit controls. The harness emits target index1 and six values
2048, changing only the first control to2049 in its changed case. Its output
must be13 bytes: the index followed by six big-endian16-bit words. These are
syntactically accepted converter fixtures, not a claim of conforming Dolby
bitstreams or correct TV trim interpretation.

Serialization operates on a copy of state and commits the copy only on success.
This is an explicit harness ownership boundary: the existing inline serializer
can mutate its candidate payload before a later validation failure. The invalid
case exposes that inner mutation while preserving outer state and emitting no
failed payload/packets. It does not assert the existing helper is transactional.

`test_native_metadata_probe.py` independently reconstructs transport packets,
checks CRC-32/MPEG-2 and a published CRC known answer, padding, packet sequence,
payload length, extension count/end, literal L1/L2/L8 bytes, scene refresh and
repeat/change counters. By default it replays the nine recorded synthetic case
outputs in `results/native-metadata-probe-libreelec-20261005a.json`, verifying fixed
case order/count, source/binary/header/library checkpoint declarations and
strict result types. Reads are capped at 1MiB+1 before parsing, with regular-file,
no-follow and descriptor/path stability checks. Regression tests reject wrong
paths, oversized/nonregular files, wrong schema/types/pins, duplicate JSON keys
and packet corruption. This is archive replay, not fresh C execution. Set
`YB_NATIVE_METADATA_PROBE` to a reviewed matching-header executable for fresh
CLI calls, or `YB_NATIVE_METADATA_ARCHIVE` to the retained original case logs.
The executable option takes precedence. If none is available, four native
assertion tests explicitly skip; no serializer success should then be reported.

The separate three tests in `test_display_metadata_sensitivity.py` establish
that adding/changing L1/L2/L8 dictionaries does not change the source colour
configuration or its pixel arithmetic. Saved source association checks still
detect stale parsed-RPU hashes. Those opaque synthetic JSON fixtures are not
serializer or full metadata-semantic tests. Conversely, preserving wire bytes
does not establish how a TV maps the picture.

## Actual LibreELEC CPU checkpoint

The strict SDK build succeeded with GCC16.2.0 against the actual patched headers.
The SDK and installed LibreELEC `libavutil.so.61.1.102` had the identical SHA256
`16e16a2ab0f89a48c7e487d365e84f1c005f119fa8754c146daaeff40883c108`.
The VM loader resolved `libavutil.so.61` to that exact file. No library was
replaced. All three headers, executable and installed library were pinned and
unchanged after the cohort; Kodi remained active.

Nine fixed cases ran CPU-only in a fresh512MiB/zero-swap systemd scope:
eight accepted cases containing12 successful serialization records, and one
deliberate duplicate-L1 rejection. Four independent wire assertions, the CRC
known-answer test and three metadata/source-association sensitivity tests passed
with no skips against the archived actual outputs. Default public-checkpoint
replay passes ten tests, including the two later-added checkpoint-reader
regressions, without invoking C or any device.

The report separates executed C/cohort-script hashes in `source_sha256` from
the final test/documentation hashes in `analysis_sha256`. The latter were
updated after the measured cohort for public replay and publication checks;
they must not be presented as the exact test files present during VM execution.

The final in-script `memory.peak` snapshot was4046848 bytes (about3.86MiB);
swap and max/OOM/kill events were zero. That snapshot precedes subsequent shell
and unit cleanup, so it is **not the completed unit's final lifetime peak**,
process RSS or all device memory. The systemd completion separately displayed
4.5M for the service. Its38ms runtime is an offline synthetic cohort observation,
not a playback benchmark. All successful payloads fit one packet; multi-packet
fragmentation is not exercised by these fixtures.

The public JSON retains every fixed synthetic result, including payload/packet
bytes, original log hashes and resource snapshots. These bytes contain no real
RPU or film pixels. The full original logs remain archived locally and in the
private VM test directory. `run_native_metadata_probe.sh` is the fixed executed
cohort script; its executable hash deliberately binds it to this build, not to
an arbitrary future binary.

## Build/reproduction plan

Root's capped LibreELEC SDK build should compile only this source, include the
pinned `K/tools/dvbridge` directory and matching SDK headers, and link `-lavutil
-lm` using that SDK. For example, with the SDK compiler environment already
selected: `$CC -std=c11 -O2 -Wall -Wextra -Werror -I<K/tools/dvbridge>
native_metadata_probe.c -lavutil -lm -o native_metadata_probe-sdk`. Existing
headers are unmodified; do not suppress an ABI mismatch by defining stand-in
types. Run the resulting CPU-only executable and the four native assertions in
a matching Linux environment with the existing512MiB/zero-job-swap ceiling.
No GPU dispatch or runtime playback integration is necessary.

Record source, binary, compiler command/version, loaded `libavutil` identity and
the three dependency hashes before/after runs. Source inspection pinned these
actual build dependencies on2026-10-05:

- Kodi `tools/dvbridge/dvbridge_metadata.h`:
  `da799ab08381318601bb0a3f8a1a74ed3293ca09b2cdde52228ea6f7e4c06d36`
- Kodi `tools/dvbridge/mpv_dvbridge_cm4.h`:
  `f6762808f5d7a5824983d72b0188098f19e86bd2a6db7b997ef63e2d35612661`
- SDK `usr/include/libavutil/dovi_meta.h`:
  `f860511cb8be3c992b4ef7da6747d8dc9670d64d276aeab3a7e6867112857a02`

This stage adds no production code, no fitted SK4 target, no LLDV backend and no
claim of HDMI interoperability or Dolby conformance. Successful synthetic
serialization is a necessary local transport check, not proof of displayed
colour accuracy.
