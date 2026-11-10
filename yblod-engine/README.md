# Native source-domain renderer — work in progress

See [LICENSE](LICENSE) and [source references](SOURCES.md) for distribution
terms, implementation scope and limitations.

Since YBLOD 0.4.0 the Dolby Vision renderer is the Vulkan engine in `vk/`
(big-fella's dv-engine-vk with YBLOD's additions, packaged by
`packages/graphics/yblod-engine-vk`, `libdv_engine_vk.so.1`). It keeps decoded
VAAPI surfaces on the GPU, reconstructs the source signal and writes the
tunnel picture with matching metadata for TV-led output, or converts to HDR10.
Its `build.rs` compiles YBLOD's host C from `src/` (tables, the metadata
serializer, `dv_ffmpeg_metadata.c`, plan inputs). The OpenCL engine
(`libdv_source_private`, OpenCL kernels and runtime packages) and the
libplacebo compatibility renderer in Kodi were removed in 0.4.0; their
sources in `src/` that the Vulkan build does not use are left to the engine
work (0.4.0 workstream A, engine side).

Everything specific to the Dolby Vision pipeline lives in this folder: the engine
(`src/`, `tests/`, `integration/`), its patches for Kodi, FFmpeg, libplacebo and the
kernel (`patches/<package>/`, linked into LibreELEC's patch folders), tools (`tools/`),
docs (`docs/`) and licences (`licenses/`, `LICENSES/`). See `../yblod/README.md`.

`CMakeLists.txt` builds only the host C's CPU contract tests (no playback
dependencies):

```
cmake -S yblod-engine -B build-native -DCMAKE_BUILD_TYPE=Release
cmake --build build-native --parallel 4
ctest --test-dir build-native --output-on-failure
```

These synthetic tests cover the polynomial/FEL reference, the order-two
specialization gate, geometry and output-slot ownership; they are not movie
playback, GPU accuracy or Dolby conformance tests. The engine's own tests
and golden hashes are in `vk/` (`cargo test`, `golden.sh`).

Source references and distribution terms accompany
the code. Qualification applies to the exact packaged image identified in each
report. Do not substitute an earlier test binary as proof that a different
integrated image was built or qualified.
