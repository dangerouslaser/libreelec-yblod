# Genuine decoder metadata ingestion diagnostic

`engine/experimental/native_decoder_ingestion.c` is the authoritative source;
the reference-directory name is a relative compatibility symlink. It is an
offline, CPU-only diagnostic, not a Kodi
integration or a complete playback engine. It uses the actual matching patched
FFmpeg headers and libraries. It never constructs `AVDOVIMetadata` from JSON.

The caller supplies a bounded raw HEVC enhancement-layer window, the expected
raw RPU NAL, a local presentation index, its expected demuxed packet position and
size, the window SHA-256, and the three expected decoded active-plane SHA-256s.
The last argument names a fresh private binary output. Inputs and output must
remain outside the public repository. Run in a private directory under the
existing 512 MiB memory limit and zero job swap; compile with one job. The caller
must verify those limits before and after execution and reject new OOM/max
events. There is no GPU, display, HDMI, or Kodi operation.

The diagnostic:

- Opens inputs nonblocking, then requires regular nonsymlink files through owned
  descriptors; rejects windows over 4 MiB. Each source hash is bounded to its
  initial exact size, checks EOF and descriptor stability, and is repeated after
  decoding. Packet association must lie within that source extent.
- Opens a fresh single-thread software HEVC decoder and sequentially decodes from
  the window beginning. No decoder seek, flush/reuse reconstruction, or arbitrary
  time-offset inference is performed. Demux probing may rewind input bytes.
- Limits dimensions to 1920×1080 and bounds packet/frame counts to 96. Packets
  cannot exceed 4 MiB. These bounds are diagnostic restrictions, not format rules.
- Requests `AV_EF_CRCCHECK | AV_EF_EXPLODE` and latches every FFmpeg warning/error.
  The latch matters because the HEVC decoder can swallow a failed RPU parse.
- Requires raw RPU and expanded metadata on the first decoded frame and target.
  This establishes observed initialization, not a universal random-access rule.
- Associates the target with a decoder-propagated packet identity using
  `AV_CODEC_FLAG_COPY_OPAQUE`; verifies exact local packet position and size.
- Compares the raw side-data payload to the expected NAL after its two-byte HEVC
  header. The expected input has no Annex-B start code; it preserves emulation
  prevention bytes. No guessed NAL/RBSP conversion is applied.
- Hashes only active rows of all three decoded 10-bit little-endian EL planes,
  excluding allocation padding, and requires exact saved-plane identity.
- Passes the target frame's actual decoder-owned expanded side data directly to
  `yb_dovi_to_integer_configs`, then copies the owned canonical instructions.

Success writes a mode-0600, exclusive-create binary object and emits a small JSON
result. The binary uses the native adapter's **same-build structure layout**, not
a portable serialized ABI. Its build record must pin the instruction size,
adapter ABI, source/header hashes, executable and matching FFmpeg library hashes.
The result's instruction hash can reveal association with private metadata and
must remain private unless intentionally approved. Public checkpoints should
retain only fixed approved scalar results and diagnostic source/build pins.
Failure never emits a successful result. Cleanup removes an output only if its
current path still names the regular-file device/inode created by this process;
if identity cannot be established, it leaves the file for private inspection.
Existing outputs are never overwritten. The output parent must be a private,
exclusively controlled directory; the identity check does not make adversarial
concurrent directory mutation safe.

For the existing frame-2296 extraction, the raw EL window's local presentation
index is 64. That index is **not original source PTS**: raw HEVC loses container
timestamps. Exact raw-RPU and decoded-pixel matches associate this diagnostic
with the saved extraction; externally verified original timing remains a separate
provenance fact. CRC acceptance means FFmpeg's requested check did not report an
error; it does not authenticate content or prove licensed Dolby conformance.

Whole-frame reconstruction is verified separately; see the
[bridge result](NATIVE_DECODER_FRAME_BRIDGE.md) and
[published checkpoint](results/native-decoder-frame-2296-20261005a.json).
That check feeds these owned instructions to the C arithmetic adapter alongside
independently verified prepared pixel planes and compares all twelve saved
stages in bounded chunks.
Prepared manifests may locate and verify pixels, but must not supply the decoder
instruction configuration in that path. Hardware scaling, fractional precision
policy, colour conversion and TV-led transport are not exercised here.

## Matching SDK build

Build against the actual patched LibreELEC SDK, not substitute headers or
fabricated FFmpeg ABI structures. With the whole repository mounted read-only at
`/repo` and the matching LibreELEC build tree at `/build`, the tested GCC 16.2
command is:

```sh
/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain/bin/x86_64-libreelec-linux-gnu-gcc \
  -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
  -fno-fast-math -ffp-contract=off \
  -I/repo/engine/include -I/repo/engine/experimental \
  /repo/engine/experimental/native_decoder_ingestion.c \
  /repo/engine/experimental/native_dovi_adapter.c \
  /repo/engine/src/native_composer.c \
  -o /out/native_decoder_ingestion -lavformat -lavcodec -lavutil -lm
```

The build ran with one CPU, 512 MiB memory, zero container swap, no network, and
read-only sources. The decoder, format and utility shared libraries in that SDK
and on the LibreELEC VM were byte-for-byte identical. Runtime version and adapter
ABI/size checks also passed. This diagnostic remains outside the default core
library build.

## Verified decoder-stage result

The reviewed private frame-2296 cohort decoded 65 frames from a fresh context and
sent 65 packets. Target local presentation index 64 passed:

- Actual decoder-provided expanded metadata directly translated by the C adapter.
- Exact 379-byte raw RPU payload identity, preserving emulation prevention bytes.
- Exact active-row SHA-256 identity for all three decoded enhancement-layer planes.
- Explicit CRC-check/strict-rejection flags and zero FFmpeg warnings or errors.
- Owned canonical instruction output, 9,216 bytes, adapter ABI version 1.

The recorded pre-exit cgroup memory-peak snapshot was 37,830,656 bytes (36.08 MiB).
Memory limit was 512 MiB, job swap limit/current were zero, and memory max/OOM/kill
events remained zero. Kodi was active before and after. This is a bounded 1080p
decoder diagnostic, not a 4K playback memory requirement or frame-rate benchmark.
Original source PTS verification is explicitly **false** for this raw-window
decode; exact RPU/pixel association is not a claim of retained container timing.

Six rejected diagnostic cohorts were retained privately before this success. No
acceptance gate was loosened. Two transport/provenance issues were isolated:

1. The saved Annex-B window ended with the exact canonical RPU NAL followed by
   exactly one extra EOF zero; the canonical NAL ended with its nonzero `0x80`
   stop byte. FFmpeg includes this transport byte in its raw-NAL extent even
   though semantic bit-length handling removes trailing zeros. The diagnostic
   fixture helper verified both original hashes, the precise final NAL extent and
   exact single-zero relationship, then wrote a new private fixture without that
   one byte. Originals remained unchanged. This is not generic zero stripping or
   a production RPU-normalization policy.
2. The saved FFmpeg 6.1 packet offset owned the three-byte suffix of a four-byte
   AUD start code, assigning its first zero to the previous packet. The current
   FFmpeg 9 parser owns the complete four-byte prefix. Independent source-byte and
   parser-code inspection predicted the exact new packet extent before it was
   accepted. `verify_aud_boundary` reproduces this narrow relation without looking
   at decoder results, guessing timestamps, or searching for a closest frame.

The fixture helper's 14 synthetic tests cover delimiter forms, exact-tail and
prefix rejection, source hashing, nonsymlink/nonblocking input, exclusive output,
NAL headers and AUD boundary prediction. Real RPU bytes, film pixels, private
instruction objects and their identifying hashes are not public artifacts.

This producer module establishes the decoder-to-owned-instructions connection
only. Its separate bridge comparison has now verified whole-frame arithmetic
against the saved native-C baseline. Hardware scaling/fractional handling,
colour, Kodi integration, display transport and SK4 output differences still
require separate evidence; no new picture-accuracy or real-time-playback claim
follows here.
