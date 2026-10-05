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

## Layout and compatibility

- `src/` and `include/`: authoritative default-library sources and public headers.
- `tests/`: native smoke test and independent installed-package C++ consumer.
- `cmake/`: package configuration template.
- `experimental/`: exact sampling, informative resampling, precision diagnostics,
  frame integration and decoder-metadata adapter sources. These are deliberately
  excluded from the default library and installation. They are not promoted to
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
