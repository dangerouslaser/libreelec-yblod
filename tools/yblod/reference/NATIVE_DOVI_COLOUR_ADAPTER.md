# Decoder-expanded Dolby colour → native configuration

The optional experimental C adapter copies FFmpeg `AV_FRAME_DATA_DOVI_METADATA`
into an owned native colour configuration. It compiles against the actual
matching `dovi_meta.h`; FFmpeg remains outside the arithmetic core.
There is no raw RPU parser, frame pairing, metadata reuse/CRC verification,
display-management extension processing, target default, TV fitting or playback.

The caller supplies target YCC/LMS matrices, offsets, explicit PQ-domain policy
and code scale4096. The caller also declares known uncompressed source DM;
FFmpeg expanded side data does **not** expose that compression history. Unknown
or compressed declarations are rejected, not inferred from matrix contents.

Supported source signal fields match `ColourConfig.from_dm`: EOTF65535, zero
EOTF parameters, bitdepth12, colour-space0, chroma-format0, full-range1.
Header requires the supported type2/format18 normalized12-bit reconstruction.
Matrix rationals must represent signed16-bit coefficients at scales8192/16384;
offsets must represent unsigned32-bit coefficients at scale2^28. Reduced
equivalent rationals are accepted; invalid denominators/non-dyadic/out-of-range
values reject without changing output. Target finite/invertible validation
uses existing `yb_colour_init`, with no fallback or implicit defaults.

Matching FFmpeg parser caveat: when raw unsigned offsets exceed INT_MAX it
right-shifts numerator and denominator to fit AVRational, potentially losing
one raw low bit for odd values. This adapter preserves the **decoded rational**;
it cannot recover raw syntax that FFmpeg no longer exposes. No raw-bit-exact
conversion claim is made for that case. Profile-specific offset interpretation
has already happened in the decoder; this adapter validates its supported
2^28 representability, not the originating stream profile.

Metadata layout is bounded to1MiB; every header/mapping/colour/extension region
is checked for bounds/alignment/overlap before FFmpeg accessors. Destination
must not alias either source allocation. Every failure leaves destination
unchanged; caller retains actual allocation/stable ownership obligations.
Successful source/target copies remain valid after inputs are released.

Synthetic tests use actual FFmpeg headers with manually owned struct fixtures,
not a fake ABI. They do not claim FFmpeg allocation/parser execution or actual
movie side-data processing. Set `YBLOD_FFMPEG_INCLUDE_DIR` for host compilation;
optional SDK probe replay uses `YBLOD_DOVI_COLOUR_PROBE_BINARY`.
