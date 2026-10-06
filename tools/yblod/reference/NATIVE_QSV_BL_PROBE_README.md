# Raw base-layer comparison probe (experimental)

This source has not yet been compiled or run. It does not establish Kodi playback,
Dolby output accuracy or performance. It downloads diagnostic pixels only; the
proposed playback route must retain direct QSV-to-VAAPI hardware mapping.

The probe sends private byte-identical packet clones from one ordinary MKV demux
to independent native HEVC/VAAPI and opt-in `hevc_qsv dovi_metadata=1` decoders.
It accepts Profile 7 with BL, EL and RPU configuration flags, and selects three
exact original Kodi-style microsecond timestamps without substitution. Returned
P010 active samples, properties and resolved public Dolby metadata are compared
exactly. Coded padding is excluded; malformed or unaligned buffers fail closed.

Prerequisites include a reviewed isolated candidate FFmpeg runtime and headers
with this repository's Dolby metadata ABI, and recorded byte identity of native
HEVC, HEVC parser, RPU parser and VAAPI HEVC sources against the original build.
The native reference is independently decoded, not reconstructed from candidate
metadata. Missing metadata, unknown extension levels and property differences
fail qualification. Inactive coefficient slots and full raw-trailer capacity are
compared strictly, assuming zero-initialized decoder exports.

Compile only, using fresh output and read-only SDK/source/runtime mounts:

```sh
docker run --name UNIQUE_CPU_BUILD --memory 512m --memory-swap 512m --cpus 1 \
  --network none -v "$SDK_PROJECT:/build:ro" -v "$PUBLIC_PROJECT:/work:ro" \
  -v "$FRESH_OUTPUT:/output:rw" -v "$ISOLATED_FFMPEG:/candidate:ro" \
  -e SDK_ROOT=/build/build.LibreELEC-Generic.x86_64-13.0-devel/toolchain \
  -e PUBLIC_ROOT=/work -e PROBE_OUTPUT=/output \
  -e BL_FFMPEG_INCLUDE=/candidate/include -e BL_RUNTIME_LIB_DIR=/candidate/lib \
  sha256:40b586615eae489cab72f139f659b81360da4c9e0b0787fadc5cba0119d9b29e \
  bash /work/tools/yblod/reference/build_native_qsv_bl_compare_probe.sh
```

Do not run media using this compile helper. A separately reviewed hardware
controller must pin executable/runtime/code/driver identity, preserve the user
player's idle state, cap memory at 512 MiB without swap, use one CPU, expose only
the specified render node and read-only input, and enforce an external deadline.
The live ready/ack collector must verify the actual child, GPU and loaded code
before its first QSV pixel readback. Raw input, frames, RPU bytes and content
hashes remain private; public results may contain only equality/count scalars.

The private CLI is `probe INPUT_MKV RENDER_NODE SEEK_US PTS1_US PTS2_US PTS3_US`.
Exact previous-RPU inheritance/no-RPU coverage is not yet established: raw RPU
side-data presence is reported per selected frame, but that alone does not prove
every AU's inheritance transition. The probe does not drain EOF; all exact
targets must arrive within the bounded input window. Target-host qualification
and full reconstructed-picture/playback comparisons remain separate requirements.
