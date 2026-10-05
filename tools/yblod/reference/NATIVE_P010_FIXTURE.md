# Native P010 diagnostic fixture packing

`native_p010_fixture.c` is a row-streamed C test-input adapter, not a production
decoder, resampler or Dolby reconstruction policy. It accepts three separate,
tightly packed, little-endian unsigned16 planes containing low-aligned native
10-bit Y/Cb/Cr codes in planar 4:2:0. It validates every code is in0..1023 and
stores exactly `code << 6` in P010: all Y rows, then interleaved Cb/Cr rows.
No colour conversion, clipping, rounding, filtering or pixel fitting occurs.

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
  engine/experimental/native_p010_fixture.c -o native_p010_fixture
./native_p010_fixture Y.u16le Cb.u16le Cr.u16le NEW_OUTPUT.p010 1920 1080
python3 -m unittest discover -s tools/yblod/reference \
  -p test_native_p010_fixture.py
```

Dimensions must be even integers2..8192. Each input must be an exact regular
plane, opened without following its final symlink and nonblocking to reject
FIFOs without hanging. Source planes cannot alias the same inode. Active reads
are exact and bounded; each input's device/inode, size, mode and nanosecond
mtime/ctime are compared before/after, with EOF checked after the expected
extent. These observations do not replace caller-owned content hashes or
guarantee immunity to a privileged concurrent writer.

Use a fresh private0700 parent directory. Output creation is exclusive, without
following its final symlink, mode0600, and never replaces an existing path.
Failure after creation removes only a still-regular path matching the created
device/inode. A concurrent hostile parent-directory writer is outside this
private-fixture contract. Successful output is flushed, exact-sized and closed
before completion is reported. Working buffers total56KiB, independent of image
height. Files/hashes/results containing movie pixels remain private and ignored.

The caller must pin helper source, executable, input planes and metadata-frame
association before/after; independently unpack every P010 word against the
original native plane codes before using the fixture. The helper's generic
completion JSON is not a decoder-frame or hash-association proof by itself.

The nine synthetic CLI tests cover code extrema and U/V order at multiple
dimensions, malformed plane extents, late invalid codes and owned-output
cleanup, existing/symlink outputs, input symlinks/FIFOs, source aliases and
malformed dimensions. They do not submit any GPU work.

For a target build, use the existing configured LibreELEC SDK compiler, with
the SDK and whole repository mounted read-only in a no-network container,
one CPU,512MiB memory and the same512MiB memory+swap ceiling. Compile the same
strict flags above; no libva or FFmpeg dependency is needed by this helper.
Record the executed compiler command and source/binary hashes separately.

## Hardware-test boundary

The P010 fixture supports private advertised P010420 scaling observations.
An isolated probe must first prove exact copy and submitted native-size
preservation before repeated enlargement. Preserve every downloaded raw bit:
whole-code reconstruction requires all low6 bits to be zero, not an implicit
mask, rounding rule or clamp. GPU synchronization, actual image pitch/offset
checks, bounded memory and source/runtime identity belong to the caller/probe.

This does not qualify the different production P010→Y416444 fractional route,
identify licensed Dolby filters, validate AMD hardware, demonstrate SK4 accuracy
or measure steady-state playback. Do not select a fractional quantizer or change
production precision based on a whole-code diagnostic.
