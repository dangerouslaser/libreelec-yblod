# Python-free native core build

The standalone CMake target builds a static library from `native_composer.c`,
`native_colour.c` and `native_y416.c`. It does not link Python, Kodi, libplacebo,
a decoder or a GPU API. Diagnostic precision probes and timing harnesses are
deliberately excluded from the core library.

```sh
cmake -S tools/yblod/reference -B target/native-core \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PWD/target/native-install"
cmake --build target/native-core --parallel 1
ctest --test-dir target/native-core --output-on-failure
cmake --install target/native-core

cmake -S tools/yblod/reference/native_cmake_consumer -B target/native-consumer \
  -DCMAKE_PREFIX_PATH="$PWD/target/native-install"
cmake --build target/native-consumer --parallel 1
ctest --test-dir target/native-consumer --output-on-failure
```

The installed package supplies `Yblod::yblod_native` through
`find_package(YblodNative 0.1 CONFIG REQUIRED)`, with headers and transitive libm
linking. The C++ consumer checks the exported package and C header linkage.
The native C smoke test checks mapping, correction, addition, final rounding,
identity colour conversion and lossless little-endian transport decoding.

GCC or Clang with signed `__int128` is required. The library uses C11 and PIC;
the colour source explicitly disables fast-math and floating-point contraction.
IPO is disabled in this target. Do not override these arithmetic constraints
with unvalidated aggressive global compiler/linker options.

## Verified target checkpoint

On 2026-10-05 the library and C smoke test built on Ollie with host GCC13.3.0
and with the existing LibreELEC SDK's GCC16.2.0, using CMake4.4.3. The host smoke
passed, installation succeeded, and the separate installed C++ consumer built
and passed. The LibreELEC-target smoke executable also passed on the Petunia
VM without Python. It exercised all three compiled core components.

Each build used one compiler job and a512 MiB memory ceiling, with job swap
disabled. The SDK ran inside the existing build container with SDK/source
mounts read-only and output confined to a fresh ignored target directory.
SDK compiler wrappers assume `/build`; simply executing such a wrapper outside
its expected container can fail and is not a valid SDK compatibility test.

Only a small standalone test executable was copied into the fresh native
benchmark directory on the VM. Kodi remained running; no renderer, image,
HDMI mode or playback default was replaced. This proves native build/link/run
compatibility—not end-to-end playback performance, GPU integration, complete
Dolby display management, or improved SK4 matching.

Python can continue generating fixtures and checking the C library, but it is
not a runtime dependency of this native core. Runtime RPU parsing, decoder
integration, hardware-surface ownership, registration/precision policy and
metadata/presentation handling remain separate integration work.
