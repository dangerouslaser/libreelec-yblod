# Standalone native reconstruction foundations

This directory is the authoritative C source for the experimental YBLOD engine
in this repository. It can be copied and built independently of the LibreELEC
and Kodi source trees. It is not yet a complete playback engine or a licensed
Dolby Vision implementation.

The default C11 static library builds only the tested integer composer, colour
conversion and lossless Y416 transport components. It has no Python, Kodi,
FFmpeg, libplacebo or GPU dependency. GCC or Clang with signed `__int128` is
required; colour arithmetic disables fast-math and floating-point contraction.
The platform math library is linked where required.

## Build, test and install

From the repository root:

```sh
cmake -S engine -B target/native-core -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PWD/target/native-install"
cmake --build target/native-core --parallel 1
ctest --test-dir target/native-core --output-on-failure
cmake --install target/native-core

cmake -S engine/tests/consumer -B target/native-consumer \
  -DCMAKE_PREFIX_PATH="$PWD/target/native-install"
cmake --build target/native-consumer --parallel 1
ctest --test-dir target/native-consumer --output-on-failure
```

For a standalone copy of this directory, substitute `-S .` and
`-S tests/consumer`. The installed package remains `YblodNative` version 0.1,
with target `Yblod::yblod_native`; installed public header filenames are unchanged.

## Optional Linux playback integration candidate

The default remains dependency-free and core-only. Explicitly opt in to the
experimental VAAPI/EGL/decoder-metadata library with:

```sh
cmake -S engine -B target/native-playback \
  -DYBLOD_BUILD_EXPERIMENTAL_PLAYBACK=ON -DCMAKE_BUILD_TYPE=Release
cmake --build target/native-playback --parallel 1
ctest --test-dir target/native-playback --output-on-failure

cmake --install target/native-playback --prefix "$PWD/target/native-playback-install"
cmake -S engine/tests/playback_consumer -B target/native-playback-consumer \
  -DCMAKE_PREFIX_PATH="$PWD/target/native-playback-install"
cmake --build target/native-playback-consumer --parallel 1
```

This adds `yblod_playback_native` (installed as
`Yblod::yblod_playback_native`), linking the native core plus actual FFmpeg
libavutil, EGL and libva. Matching decoder-expanded Dolby metadata headers and
libraries are required; the tested LibreELEC SDK uses libavutil 61.1.102, EGL
1.5 and libva 1.24.0. The installed package rejects a different libavutil ABI
major from its build.
This version check does not identify custom metadata patches: consumers must
also use the matching patched Dolby metadata headers and runtime ABI.
OpenGL development headers must be available. No Kodi,
Python or libplacebo is needed to build this standalone integration library.
Shader sources and candidate headers are installed only with this option.

The library compiles real guide/phase, composer, reconstructed-YCC, VA scaling,
DMA-BUF import, EGL sibling bridge and caller-context orchestration sources.
Its link smoke test uses actual argument guards and performs no GPU/decoder
work. The independent installed consumer resolves only the exported package
and `Yblod::yblod_playback_native`, checking public-header and transitive-link
closure without source-tree include or library paths. Its actual LibreELEC SDK
configure/build/link passed; that cross-built executable was not run.
Compilation/linking is not evidence of live playback, colour accuracy,
zero-copy, or a complete Dolby implementation. Runtime route selection remains
the integrating application's responsibility; enabling this build option alone
does not activate the candidate in Kodi.

## Layout and compatibility

- `src/` and `include/`: authoritative default-library sources and public headers.
- `tests/`: native smoke test and independent installed-package C++ consumer.
- `cmake/`: package configuration template.
- `experimental/`: exact sampling, informative resampling, precision diagnostics,
  frame integration and decoder-metadata adapter sources. These are deliberately
  excluded from the default library and installation. The explicit optional
  playback profile installs only its selected integration subset. They are not promoted to
  production by this directory move. The FFmpeg adapter requires the actual
  matching patched FFmpeg headers when separately built.

The historical `tools/yblod/reference/` paths are compatibility links, not
independent source copies. Its old CMake entry point remains available. Python
reference tools, synthetic fixtures, published observations and integration
documentation remain there; Python is test tooling, not a runtime dependency
of the default native library.

SDK/container builds using compatibility links must mount the whole repository
read-only, not just `tools/yblod/reference/`, or use a materialized standalone
`engine/` tree. Keep output in a separate writable directory and build with one
compiler job under the existing memory ceiling.

This reorganization changes neither processing rules, public C ABI, licensing,
playback defaults nor existing evidence claims. Hardware surface ownership,
fractional enhancement samples, decoder pairing and presentation still require
integration work.
