# Decoder-owned instructions to full-frame C reconstruction

`native_decoder_frame_bridge.c/.h` accept an exact-size, same-build instruction
blob produced by the separately reviewed decoder diagnostic. This is not a
portable format, RPU parser, authentication mechanism, or playback integration.
The C bridge copies the blob into aligned owned storage, checks its version and
supported declarations, and passes its mapping/NLQ configurations to the existing
validated C frame integration boundary. Failure leaves the context untouched.
Disabled NLQ is checked field by field; structure padding has no semantic role.

`native_decoder_frame.py::compare` is an offline private test harness. Compile a
shared library from the bridge, integration, composer and sampling C sources
using strict warnings. The caller must pin that build's complete source inventory,
compiler command, ABI and library hash; the harness checks version/size queries
and the supplied library hash before use. Do not load an untrusted library.

From the repository root, a host diagnostic build is:

```sh
cc -std=c11 -O2 -fPIC -shared -Wall -Wextra -Werror -Wconversion -Wshadow \
  -Iengine/include -Iengine/experimental \
  engine/experimental/native_decoder_frame_bridge.c \
  engine/experimental/native_integration_probe.c \
  engine/experimental/native_sampling_probe.c engine/src/native_composer.c \
  -o /path/to/fresh-private-directory/libnative_decoder_frame.so
```

The canonical bridge C/header live under `engine/experimental`; reference-folder
compatibility links preserve existing imports/tests. The bridge build itself
does not need FFmpeg headers or libraries: it consumes the adapter's owned native
instruction type, not an `AVDOVIMetadata` allocation. Use the actual LibreELEC SDK
compiler instead of `cc` for target builds. The genuine decoder producer remains
a separate matching-FFmpeg build. Run focused host tests from
`tools/yblod/reference` with `python3 -m unittest -v
test_native_decoder_frame_bridge test_native_decoder_frame`.

The reviewed target build used the existing LibreELEC SDK's GCC 16.2 compiler:
`/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain/bin/x86_64-libreelec-linux-gnu-gcc`.
Inside the existing `libreelec-dv-build:latest` container, mount the LibreELEC
build tree at `/build:ro`, this complete repository at `/source:ro`, and a fresh
private output directory at `/out`. Use the command above with that compiler,
absolute `/source/engine/...` source/include paths and
`/out/libnative_decoder_frame.so`. Build with `CCACHE_DISABLE=1`, no container
network, one CPU, `--memory 512m --memory-swap 512m`; this prevents job swap.
The canonical shared bridge compiled successfully with all listed warnings as
errors. This is build evidence only, not a target execution or real-frame result.

The harness accepts the decoder-produced private blob and its independently
verified digest. Prepared manifests locate and hash pixels, identify geometry,
and establish association with the saved native baseline. Their coefficients
never initialize this processing path. The harness reads only fixed blob header
scalars for the descriptor; the C bridge validates them authoritatively. Declared
sample depths and enabled-EL consumption must agree, and decoded MMR requires an
explicit prepared guide. No fractional sample policy is chosen.

All twelve stage outputs are compared byte for byte in chunks of at most 65,536
samples. No duplicate frame files are produced. Input, baseline, blob, library
and local dependency identities are rechecked before success. The caller must
run under at most 512 MiB with zero job swap; before/after memory guards reject
changed limits, swap usage or new max/OOM events. Bypassing the memory guard is
an explicit synthetic host-test option, not measured production evidence.

The returned evidence is **private**: it includes the instruction digest and
input associations. This helper intentionally has no public checkpoint writer.
A caller publishing results must separately whitelist approved scalars and
source/build pins and must not copy metadata, paths, exception text or arbitrary
private report keys. The producer's CRC/raw-RPU/decoded-EL association report and
FFmpeg library identity remain separate required evidence; a digest by itself
does not prove that a blob came from genuine decoder side data.

Six initial synthetic host tests pass: owned-copy/size, header rejection,
disabled NLQ, aliases, full-stage polynomial/MMR/disabled comparisons across
different chunk sizes, and corrupt/truncated blob rejection. Synthetic fixture
construction in tests is not genuine decoder ingestion. No real-frame run,
licensed conformance, GPU, colour, display or real-time performance is claimed.
