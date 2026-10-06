# Picture association versus packet transport timing

This is a new, explicit `picture-association.v2` test contract. The prior strict frame-property diagnostic and its failures are preserved. No product timestamp is rewritten to make the comparison pass.

FFmpeg's `AVFrame.pkt_dts` describes the packet that triggered returning a frame. The generic decode wrapper assigns it from its current callback packet. Different decoder buffering can therefore produce different transport DTS values for the same picture. It is not the immutable picture identifier.

## Mandatory picture checks

Every admitted AU must return once on both routes in the controlled window. Returned PTS and known best-effort timestamp must equal the registered unique source PTS, and duration must equal that AU's duration. Independent native Dolby metadata and raw RPU presence/bytes must agree. All previously compared geometry, crop-origin, flags, picture type, chroma siting, color and other picture properties remain mandatory.

The three selected pictures still require literal equality of every active P010 sample in all nine planes, with valid low-bit layout. Both decoders must complete the controlled NULL-drained window without missing events or pending snapshots. This is not a natural full-film EOF test.

## Nonqualifying transport observations

The report separately counts every paired frame's equal/different/unknown transport DTS. Known numeric deltas use overflow-safe 128-bit subtraction and unsigned 64-bit magnitudes. Unknown timestamps have no fabricated numeric delta.

Selected frames report legacy full-property equality, picture-property equality, and transport-DTS equality separately. The observer checks their relationship; a legacy mismatch is not relabeled full equality.

This contract initially supports lifecycle OFF only. Lifecycle ON fails closed until its epoch contract is separately updated. It does not prove Kodi forwarding of packet durations or full player scheduling. Kodi runtime must independently confirm known matching presentation timestamps rather than relying on its DTS fallback.
