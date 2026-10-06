# QSV base layer Dolby metadata foundation

The association foundation keeps each decoded picture linked to its own immutable Dolby instructions, even when output is reordered. It is CPU tested only. It does not enable QSV playback, parse access units, or attach metadata to FFmpeg frames yet. Existing VAAPI behavior remains unchanged.

## Association ownership

`qsv_dovi_association.h` provides a bounded table of 64 picture identities. A caller prepares one snapshot before hardware submission. Preparation takes ownership but does not publish the snapshot or change the committed identity generation. Hardware retries retain the same prepared identity. Commit performs no allocation and publishes the prepared entry only after the complete access unit is accepted. Returned identities transfer ownership to the caller; unknown or duplicate returns leave the caller output untouched.

Cancellation and flush release owned snapshots. A cancelled identity is retired because hardware may have consumed part of an access unit. Identity generation never resets across seek. Source timestamps may repeat; internal identities do not. A null snapshot represents a correctly associated picture without Dolby metadata, not a missing association.

The caller must make an independent deep copy of Dolby parser state before parsing, construct the immutable metadata snapshot, and prepare this table entry before submission. After accepted submission, it commits the table and replaces the active parser state using allocation-free ownership operations. Allocation failure or EAGAIN must not advance the active Dolby state. This module does not implement that parser transaction.

FFmpeg provides `ff_dovi_ctx_replace`, not a deep-clone API. It copies mapping/color pointers and shares refcounted mappings, color data and extension blocks (`dovi_rpu.c:59–72`). The parser writes existing mapping and color allocations in place (`dovi_rpudec.c:553–561,674–682`), so using this shallow replacement to prepare a transaction would mutate committed state. Integration needs a private deep-copy helper with pointer rebasing, or a separately reviewed copy-on-write parser change. Neither exists in this foundation.

Initialize the association table to zero with a nonnull release callback. Calls must be serialized and the release callback must not re-enter the table. Cancel and flush require this valid initialized table. Failed preparation retains caller ownership of its snapshot.

## Required FFmpeg integration

The proposed HEVC_QSV option remains disabled by default. Use FFmpeg's existing `ff_h2645_packet_split`, `ff_dovi_rpu_parse`, `ff_dovi_get_metadata`, and `ff_dovi_ctx_replace` for resolved-state publication rather than a new Dolby parser. Independent state preparation requires the additional deep-copy work described above.

Gate initial input to exactly one complete progressive picture per access unit. Count layer-zero VCL NALs whose `first_slice_segment_in_pic_flag` is set; continuation slices do not create new pictures. Validate NAL headers before inspecting that flag. Reject multiple pictures, unsupported layers, fragmented pictures, and RPU-only input that cannot be associated unambiguously. Select the trailing valid layer-zero, temporal-zero RPU according to the native decoder's scan. Validate trailer ordering; do not merely count NAL type 62 occurrences.

Parse once when a packet becomes the active complete access unit, never again for a partially consumed tail or retry. Keep that prepared identity and parser clone until all bytes are accepted. A returned frame for a still-prepared identity is a terminal ambiguity under this initial restricted contract; it must not be paired with another entry.

Pass the internal identity directly as `mfxBitstream.TimeStamp` instead of rescaling source PTS to 90 kHz. On return, require one exact association, attach its immutable metadata, and restore original PTS. Preserve original duration and applicable frame properties separately. No FIFO pairing, latest-state attachment, or assumed COPY_OPAQUE behavior is permitted.

The native decoder attaches the resolved Dolby state even when a picture has no new RPU. Before a valid mapping and color state exist, `ff_dovi_get_metadata` produces no metadata. Preserve this distinction. Invalid RPU behavior must follow the native parser's actual state mutations; treating every parse error as an unchanged state is not established.

Parameter changes are an explicit drain boundary. Drain and match all outstanding output before resetting/reinitializing state. If FFmpeg's existing reinitialization path cannot establish that boundary, reject the opt-in transition instead of carrying associations into a new decoder generation. At seek, clear pending associations and use `ff_dovi_ctx_flush`, which retains configuration but clears prior mappings.

## Source references

References are to the inspected FFmpeg 9.0.2 source used by the LibreELEC SDK:

- `libavcodec/hevc/hevcdec.c:3733–3770`: RPU selection and parsing before slice decoding.
- `libavcodec/hevc/hevcdec.c:3139`: resolved metadata attachment.
- `libavcodec/dovi_rpudec.c:33–84`: metadata absence and snapshot construction.
- `libavcodec/dovi_rpu.c:43`: flush semantics.
- `libavcodec/qsvdec.c:64–70,802,899`: existing timestamp rescaling.
- `libavcodec/qsvdec.c:1157–1204`: buffering and partial consumption.
- `libavcodec/qsvdec.c:1002–1022`: parameter-change draining.

## Validation status

The strict C11 CPU contract fixture passes ownership, uncommitted output rejection, retry identity, wrong/duplicate commit, reordered output, exact signed timestamps, absent metadata, duplicate source PTS, bounded capacity, cancellation, flush, stale output, and overflow checks. The isolated container used a 512 MiB memory limit, no additional swap, one CPU, no network, and no GPU access. Peak memory was 9,981,952 bytes; all memory events and swap usage were zero.

Access-unit parsing, real DOVI parser transactions, parameter-change draining, actual MFX timestamp propagation, hardware mapping, pixel equality and playback remain unqualified. Those contracts are required before adding the FFmpeg integration patch.
