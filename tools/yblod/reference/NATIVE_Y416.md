# Lossless Y416 CPU transport boundary

`native_y416.c` / `native_y416.h` unpack caller-owned CPU bytes into four
caller-owned unsigned 16-bit planes. This is transport code, not Dolby
reconstruction, an enhancement scaler, a GPU importer, or a fence/ownership API.

The descriptor explicitly declares little-endian U/Y/V/A words, 16-bit storage,
10-bit native colour significance and six fractional bits. The last two fields
describe the current tested Intel import route, **not a universal Y416 rule**.
Every colour word is returned unchanged, including low-bit fractions and words
above nominal 10-bit range. Alpha is preserved independently; the unpacker
does not interpret alpha as Q6 or require it to be 65535.

The required input extent is `(height - 1) * stride + width * 8`. Last-row pitch
padding is not required. Odd widths/heights and unaligned byte input are allowed;
this function does not impose a 4:2:0 grid. Output arrays must be aligned,
disjoint and have exactly `width * row_count` samples, at most 65,536 per call.
All descriptor, extent, arithmetic-overflow, row-region and alias checks happen
before any output is written. Validation errors leave all output arrays intact.

The caller must keep the descriptor and all allocations accessible, alive,
stable and coherent throughout the call. A const pointer does not prove that
a hardware producer has completed or that CPU access is synchronized. The API
does not guess those conditions. It performs no normalization, integer-code
rounding, clipping, downsampling or layer registration. In particular, it does
not connect raw fractional words to the integer-only reconstruction stages.

Run `python3 -m unittest -v test_native_y416` to compile a temporary library and
test literal byte order, all low-six-bit patterns, overshoot/alpha preservation,
padded rows, odd dimensions, partial regions and failures before writes.

For previously saved synthetic surfaces, a private JSON manifest can declare
`cases` containing name, path, width, height, SHA256 and source-report SHA256.
Run `python3 test_native_y416.py --archive PRIVATE_MANIFEST NEW_REPORT_JSON`.
The bounded verifier streams every word, compares native output with independent
stdlib little-endian decoding, and checks complete-file hashes. It does not
capture, replay or modify a GPU surface. Its aggregate report omits input paths
and picture words; source-report hashes remain caller-declared provenance.

## Saved hardware-surface checkpoint

Four previously saved 3840×2160 synthetic surfaces (ascending luma ramp,
descending chroma ramp, chroma step and an integer-source-offset luma stripe)
were copied read-only from the VM. Every one of their 132,710,400 U/Y/V/A words
matched independent stdlib little-endian decoding. All four complete-file
hashes also match the saved hardware-report declarations.

`native-y416-archive-validation-low-memory.json` records aggregate counts,
hashes and source pins only. The final verifier took 10.68 seconds for the
process and reported 42,860 KiB process peak RSS with zero swap under a 512 MiB
cap. The initial harness had reported 172,004 KiB; replacing a ctypes owner cast
with a borrowed address removed its large keepalive cycles. The C unpacker did
not change, and the full 132,710,400-word exact comparison passed again.

The owning input buffer remains alive lexically throughout each synchronous
native call and the independent comparison. Borrowed-address construction is
not permission to use a dead or incoherent allocation. These resource figures
include Python/ctypes verification overhead and are not playback or controlled
timing benchmarks. No new GPU job, scaling measurement or licensed accuracy
result was produced. Original surfaces remain unchanged.
