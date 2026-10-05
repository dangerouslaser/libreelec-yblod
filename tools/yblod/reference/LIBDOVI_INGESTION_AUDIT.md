# libdovi metadata ingestion audit

libdovi can read the Dolby instructions our engine needs. It cannot replace the engine: it does not reconstruct video, scale the enhancement layer, or decide how a television should display the result. The useful first step is to compare its answers with the metadata already supplied by FFmpeg—not add another required dependency to playback.

This is a read-only source review dated 2026-10-05. No dependency was built, no runtime integration was changed, and no device job was performed. Our existing pinned `dovi_tool` 2.3.4 extraction workflow remains unchanged.

## Reviewed revision and implementation

Upstream repository: [quietvoid/dovi_tool](https://github.com/quietvoid/dovi_tool/tree/614c816b6446dcd1dbaf433403d499a6026fbb5a). Exact reviewed commit: `614c816b6446dcd1dbaf433403d499a6026fbb5a`, obtained from a fresh read-only audit clone.

The [library README](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/README.md) describes a metadata read/write library, distributed as a Rust crate and C-compatible library. **C-compatible does not mean implemented in C.** The implementation is Rust, exposed through an `extern "C"` API and generated C header. Our pixel-processing engine can remain C even if an optional metadata reader uses this interface; adding libdovi would still add a Rust-built dependency.

At this revision, the [CLI manifest](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/Cargo.toml) still declares version 2.3.4, while the [library manifest](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/Cargo.toml) declares 3.4.0. The [changelog](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/CHANGELOG.md) also includes an unreleased `level253` pointer addition to the C `DmData` structure. Consequently, a CLI version string is not an ABI identity. Any future build must pin the commit, generated header, compiled library, build options, and consumed structure layout together. This audit does not claim the currently installed extractor was built from the reviewed upstream commit.

## What the C interface exposes

- [Header](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/c_structs/rpu_data_header.rs): inferred profile, available FEL/MEL classification, layer bit depths, coefficient denominator, residual-disable flag, resampling flags, and previous-mapping reference flag/ID. An inferred profile is not a conformance certificate or a substitute for validating the fields our engine supports.
- [Mapping](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/c_structs/rpu_data_mapping.rs): three component curves, pivots, polynomial orders/coefficients, MMR orders/constants/coefficients, partition information, and optional NLQ.
- [NLQ](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/c_structs/rpu_data_nlq.rs): offset, maximum, dead-zone slope and threshold, including integer/fractional coefficient portions. These are metadata values, not an implementation of our integer or fractional residual-processing policy.
- [Source/display metadata](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/c_structs/vdr_dm_data.rs): colour matrices/offsets, signal fields, source PQ limits, metadata IDs, refresh flag, and compressed-status flag. [Known extensions](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/c_structs/extension_metadata.rs) include L1/L2/L5/L8 and other supported levels. Exposing trim values is not applying display adaptation.

The [C API](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/capi.rs) accepts unescaped RPU bytes, HEVC UNSPEC62 NAL units, and AV1 metadata payloads through separate entry points. Input framing must match the selected function. Parsing can return a non-null opaque error object: callers must check `dovi_rpu_get_error`, not just the pointer. Header, mapping and DM getters allocate converted structures and need their matching free functions; absent structures can legitimately return NULL. File-list objects have their own ownership rules. Copy validated values into our owned configuration before releasing library objects.

## State and preservation limits

**Mapping reuse is not automatically resolved.** In the [RPU parser](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/rpu/dovi_rpu.rs#L175-L192), `use_prev_vdr_rpu_flag` leaves the mapping absent. The C mapping getter therefore returns NULL. NULL does not mean identity mapping. A playback integration needs the correct referenced mapping, with explicit seek/reset/missing-history behaviour.

**Compressed DM is not a complete colour configuration.** The [DM parser](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/rpu/vdr_dm_data.rs#L79-L93) reads its IDs/refresh field and initializes the remaining source fields with defaults. Validation contains an explicit note that compressed DM should obtain state. A caller must not treat those default matrix/signal values as resolved instructions.

**Unknown extension blocks are not transparently preserved.** Both [CM2.9](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/rpu/extension_metadata/cmv29.rs) and [CM4.0](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/rpu/extension_metadata/cmv40.rs) reject unknown levels before reaching the reserved-block parser. A reserved-block type exists, but that is not evidence that unknown input levels round-trip. Moreover, the C extension conversion ignores a `Reserved` variant. Known opaque level253 data has its own representation; that does not generalize to every unknown instruction.

The [RPU implementation](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/rpu/dovi_rpu.rs) checks the embedded CRC, separately retains remaining trailing payload bits, and validates the recomputed CRC when writing an unmodified parsed RPU. These useful safeguards do not establish arbitrary unknown-block preservation. Profile-conversion/editing APIs are separate and can intentionally change mapping or residual instructions; they must not be called in a pass-through ingestion adapter.

The parser's [header validation](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/dolby_vision/src/rpu/rpu_data_header.rs#L130-L173) also has its own accepted subset, including native layer depth 10 and denominator at most 23. That subset differs from our deliberately wider synthetic arithmetic test envelope. Failure to parse such a synthetic configuration is not evidence that our arithmetic is wrong, nor that every accepted real stream is supported by our renderer.

## Recommended ownership and next test

Keep FFmpeg's existing `AVDOVIMetadata` route as the likely runtime boundary: the decoder already owns access-unit/frame association and its parsing history. This is an architecture recommendation, **not a claim that we have verified every current FFmpeg reuse/reset edge case**. Our adapter must still validate supported values, copy immutable configuration, associate it with the correct frame, and refuse unresolved or unsupported state.

Use pinned libdovi first as an independent parser/oracle outside the pixel hot path. Compare normalized fields with the existing pinned extraction output and FFmpeg metadata on fixed synthetic cases: ordinary full mapping/DM, mapping reuse, compressed DM, missing history after seek, residual disabled, altered CRC, and unknown extension level. Test ownership cleanup and NULL/error distinctions. Compare data, not the visual appearance of the SK4 output. Keep original RPU bytes separately where preservation is required; do not infer preservation from decoded structures.

This would improve confidence in ingestion. It does not resolve enhancement-layer scaling, fractional sample handling, HDMI packet construction, licensed-device equivalence, or the television's display-mapping algorithm.

The upstream [MIT license](https://github.com/quietvoid/dovi_tool/blob/614c816b6446dcd1dbaf433403d499a6026fbb5a/LICENSE) allows source reuse subject to its notice requirements. It does not establish Dolby certification or resolve any separate patent/branding obligations; this audit makes no legal-clearance claim.

## Source SHA-256 inventory

Hashes below describe upstream files at the reviewed commit, not installed binaries or generated headers.

```text
875fc6ad1c353bb5cc17f153aafa812038e788c8a6e74f3a629f90c5916fcedb  Cargo.toml
e9d76c149b1176de4aa0202cfb6a4a266a0c4cb71959f429d670c3a857f95e52  LICENSE
0395429dafe734047b1a1730d2e3fa1cfaecb7d1fe60afb23b77bce11c492f72  dolby_vision/Cargo.toml
69eb3d680a4d9f2de8e7d530cfb32cf769da10ced83e9a81beaf068dd0223edf  dolby_vision/README.md
f77392228a2578a5e404b7efd8a9181eca97d74a8ad7ad69f891e57b342b9f90  dolby_vision/CHANGELOG.md
03970544c4ed694d5a8c62a7eeb24aa292e3e66b2ceefed6b6acb05405f50b93  dolby_vision/src/capi.rs
63f6669db917242444fbc1dce4f27f7275d27db0092b81bb6eed5697621d177b  dolby_vision/src/c_structs/rpu_data_header.rs
412b524dc5946fe6d874e1e8d42a66cd9938d39c3507784c46e485dbf9c51135  dolby_vision/src/c_structs/rpu_data_mapping.rs
a419cf04c0bd0c33c8c5259f68b0c83ca625b34a416022034b9c0a451405e593  dolby_vision/src/c_structs/rpu_data_nlq.rs
fff4f72d4c60838b735a723887462ac51dd4455cf6d718e9c7c60ce7d330b49b  dolby_vision/src/c_structs/vdr_dm_data.rs
36906d3cb52b854252249e14c97271dc4f047d1c5a2968a563b762c24e87e531  dolby_vision/src/c_structs/extension_metadata.rs
c8522f6fd1bd320fbe328af1e6f9886280cc8a50e86af00c433a7f6ed33efe6b  dolby_vision/src/rpu/dovi_rpu.rs
6810c89cb3dbc488b42c03226fa5c77611e3db704670d6a0b2eeae9930b72d15  dolby_vision/src/rpu/rpu_data_header.rs
6e7a4c0708b0913fcc795699d33e6e4980bd8664b1acb776626ad56d8ff6d0f3  dolby_vision/src/rpu/vdr_dm_data.rs
0eebea1148695cfe1b39cd5795197d1854803a9e280ed8f452e0168c2a1472a2  dolby_vision/src/rpu/extension_metadata/cmv29.rs
3436d76b23dd5a88b00ad688f166b90ce1fb35f70efaaab924cabecfa2796afa  dolby_vision/src/rpu/extension_metadata/cmv40.rs
```
