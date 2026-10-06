# Y416 same-storage packed-word gate

This separate synthetic 4×4 experiment requests VA Y416 with a **12-bit**
YUV444 render-target contract. It does not claim 16-bit media processing.
After upload and producer synchronization, `vaGetImage` downloads that exact
surface into Y416 storage. All 64 little-endian words are captured without
assigning semantic component names.

Two comparisons are deliberately separate:

- Upload pattern versus VA readback shows changes in the upload/surface path.
- Imported texture versus VA readback shows changes in the EGL/GL sampling path.

The exported same FD, offset, pitch, dimensions and exact 64-bit modifier are
reinterpreted as DRM **ABGR16161616 (AB48)**, only when its modifier is advertised
for ordinary texture2D import and not `external_only`. This is an explicit
same-storage format reinterpretation, not YUV conversion or native Y416 import.
Desktop GL verifies normalized `GL_RGBA16`, then `texelFetch` recovers each of
four positions by rounding normalized values times 65535 into uint32 words.
All observed words and VA reference words are public synthetic values so the
comparison can be independently checked. No position is assumed to mean Y/U/V/A.

Unsupported reinterpretation returns completed capability inventory, not a
sampling pass. A sampling pass requires actual read, 64 compared words and zero
EGL-versus-VA mismatches; upload-versus-VA changes are reported independently and
must not be hidden. No filtering, film, DV metadata, scaling or playback occurs.
This proves neither full-range16-bit accuracy nor zero-copy/performance.

The established render-node association, read-only export, bounded descriptors,
FD ownership, GPU fence and cleanup rules remain. Overall subprocess timeout
must be imposed by the caller. Imported graphics resources are released before
the VA surface and exported FDs. Host tests use UBSan, plus optional SDK CLI
guards through `YBLOD_VAAPI_Y416_IMPORT_PROBE_BINARY`.

CLI: `vaapi_y416_import_probe /dev/dri/renderD128 y416`.
Schema: `yblod.vaapi-y416-import-probe.v1`.
