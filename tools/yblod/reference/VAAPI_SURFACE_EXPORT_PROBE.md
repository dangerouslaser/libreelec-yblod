# VA-API surface-export inventory

## Completed VM gate

[Public source-pinned results](VAAPI_SURFACE_EXPORT_RESULTS.json) record both
fixed synthetic formats on Intel iHD 26.3.5, VA API 1.24. P010 exported one
12,288-byte object with two layers (R16 and GR32), offsets 0/4096 and pitch 128.
Y416 exported one 8,192-byte object/layer, offset 0 and pitch 128. Both objects
reported modifier 72057594037927938; neither was linear, so active layout
extent validation remains explicitly false. No external mapping occurred.

Producer synchronization, structural checks, descriptor ownership and cleanup
passed for both formats. Charged peaks were 10,969,088 and 10,649,600 bytes under
512 MiB, with zero job swap and memory-limit/OOM events. Kodi remained active.
Six host guards passed, including sanitizer and compiled pre-device checks.

This proves only that these synthetic allocations can be uploaded and exported
with the reported layouts. It does not establish decoder/VPP surface layout at
movie resolutions, actual pixel preservation, graphics import, zero-copy,
frame-pool reuse or playback speed. Next query/import the exact returned plane
formats and modifiers and verify a synthetic raw-word round-trip.

`vaapi_surface_export_probe DEVICE p010|y416` creates one fixed public synthetic
4×4 image, uploads it to an Intel VA surface, synchronizes the producer and
exports read-only separate layers with DRM PRIME2. It performs no decode,
scaling, Dolby reconstruction, EGL import, rendering or playback changes.

P010 requests YUV420_10. Y416 requests **YUV444_12** because that is the target
SDK's available VA render-target contract: its 16-bit storage container is not
proof of 16-bit processing. There is no output pixel readback/accuracy claim.
Allocation success is diagnostic, not a query of advertised VPP capabilities.

The JSON schema `yblod.vaapi-surface-export-probe.v1` reports vendor/API version,
format, nominal render-target precision, numeric object sizes/modifiers and
layer plane offsets/pitches. It never prints file descriptors or pixel values.
All owned descriptors from a successful export are closed, including on failed validation; image,
surface, display and device cleanup precedes the success report.
Ownership is restricted to the returned object count (bounded by four slots),
with duplicate FD values closed once and unused fields ignored. A failed export
does not transfer ownership of unspecified descriptor fields; those fields are
never interpreted as handles to close.

The validator bounds counts, object sizes, pitches, indices and offsets; linear
P010/Y416 layouts additionally check active extents and overlapping planes with
64-bit arithmetic. Tiled/compressed layouts are treated as opaque: structural
validation is not proof of their memory layout or importability, and
`layout_extent_verified` is false. No mmap or image import is attempted.

Host tests compile the pure C validator with UBSan and exercise malformed
descriptors without GPU access. Optional SDK CLI tests use
`YBLOD_VAAPI_EXPORT_PROBE_BINARY`. No actual device test is implied by those tests.

Follow-on gate: import the actual exported layout into graphics and validate
numeric samples before attempting a resident reconstruction path. Export by
itself proves neither zero-copy nor shader access nor real playback performance.

Primary contracts: [libva surface export](https://github.com/intel/libva/blob/master/va/va.h),
[PRIME descriptor](https://github.com/intel/libva/blob/master/va/va_drmcommon.h),
[Intel format/path precision](https://github.com/intel/media-driver/blob/master/docs/media_features.md).
