# Experimental CPU-readable scaled-surface handoff

`engine/experimental/native_scaled_surface.c/.h` accepts a borrowed, already
coherent CPU-readable P010 allocation. It does not perform scaling, map a GPU
surface, wait for a fence, own storage, or implement playback. Intel and AMD
callers can use the same allocation description after their own synchronization
and mapping/readback; AMD hardware has not been tested here.

ABI version 1 exposes a descriptor-size query. Supply even dimensions up to
8192, explicit byte allocation size, Y/UV offsets and strides, native10/Q6
format, `coherent_ready=1`, and separate frame/provenance tokens. Readiness and
tokens are caller assertions, not synchronization or authentication. The
allocation must remain accessible, coherent and immutable throughout a call.
Complete Y and UV extents, including inter-row padding, must be present and
disjoint. The final row requires its active bytes, not trailing pitch padding.

Components 0/1/2 select Y/Cb/Cr. A contiguous active-sample chunk of 1..65536
skips padding, reads little-endian words explicitly and produces host-endian
uint16 values. Raw mode preserves every bit, including 65535; it is a diagnostic
route, not completed Dolby arithmetic. Exact whole-code mode checks every
selected word for zero low six bits before writing anything, then shifts by six
without clipping or rounding. A fractional word rejects the entire selected
chunk. This is **not** a fractional scaling policy and does not classify other
chunks. A caller claiming a whole-code frame must preflight all active words
before arithmetic and still complete all integration component counts.

Bounds, address/extent overflow, alignment, tokens, plane overlap and descriptor,
token, allocation and destination aliases are checked before output writes.
Declared spans cannot establish actual ownership or detect concurrent mutation.
Failures leave the destination unchanged. No GPU, colour, display or licensed
Dolby correctness claim follows from these checks.

## Reproduce CPU tests

From the repository root on a normal C11 compiler host:

```sh
cd tools/yblod/reference
python3 -m unittest test_native_scaled_surface test_native_scaled_surface_chain -v
```

Python supplies synthetic fixtures and checks; extraction and chained native
composition execute in C. The chain test uses synthetic decoder instructions,
not private media coefficients. It checks enabled enhancement reconstruction,
all components and complete counts against direct integer-input C calls.

## SDK shared-library build

The default standalone engine CMake build is unchanged. This diagnostic library
explicitly combines these experimental units with the composer; it has no
FFmpeg dependency because the frame bridge consumes an already decoded,
same-build native instructions blob.

Mount the complete repository read-only at `/repo` (compatibility symlinks need
the sibling engine directory), the LibreELEC SDK read-only at `/build`, and a
fresh ignored output directory at `/out`. Run the SDK container without network,
with 512 MiB memory, no additional swap allowance and one CPU. Inside it:

```sh
/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain/bin/x86_64-libreelec-linux-gnu-gcc \
  -std=c11 -O2 -shared -fPIC -Wall -Wextra -Werror -Wconversion -Wshadow \
  -fno-fast-math -ffp-contract=off \
  -I/repo/engine/include -I/repo/engine/experimental \
  /repo/engine/experimental/native_scaled_surface.c \
  /repo/engine/experimental/native_decoder_frame_bridge.c \
  /repo/engine/experimental/native_integration_probe.c \
  /repo/engine/experimental/native_sampling_probe.c \
  /repo/engine/src/native_composer.c \
  -o /out/native_scaled_surface_chain.so
```

Record source/header and binary SHA-256 hashes for each execution. Tests on a
host compiler do not replace actual SDK/LibreELEC runtime checks. Processing
through this handoff does not establish real-time performance or a fractional
hardware-scaling contract.
