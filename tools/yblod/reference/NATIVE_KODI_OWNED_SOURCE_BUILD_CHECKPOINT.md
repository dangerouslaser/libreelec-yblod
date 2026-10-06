# Kodi custom-VAAPI source candidate build checkpoint

This checkpoint concerns the opt-in experimental reconstruction engine's Kodi
integration. It does not establish film playback, colour accuracy, sustained
performance, or supported device-loss recovery.

## Source and compiler gates

Generic08 patch SHA256:
`abda58a3d9181c3c00b2ff56bf419a9a6aa51b4b2492fcc9c862d4b5e0708b34`.
It applies after Generic06 and Generic07. The five affected post07 sources and
the previous complete materialized engine were backed up before applying 08;
backup SHA256:
`ad297bcad6503e3da91672e5d9391aa572aec9fd339372d5d7aaa5a61416b8ea`.

All four isolated actual Kodi translation units compiled successfully with the
existing SDK compile-command warning/include configuration, sequentially at
`-O2 -fno-lto`, under a 512 MiB memory/no-swap/one-CPU container limit:
VAAPI, DVBridgeGLES, LinuxRendererGLES, and RendererVAAPIGLES. These are compiler
checks, not a linked Kodi runtime test. The ephemeral compiler container did
not capture its memory peak or memory events; the limit is not a measured peak.

The materialized engine uses playback create ABI 2. Its context header SHA256 is
`3e7e83ff4a6b191a7bc5be42eae0742ba54ec14ce14b2dcee71522c969fc41fb`.
The full build rebuilds the actual native context C source and its archive;
it does not substitute a fake object or a prebuilt standalone archive.

## Complete incremental dependency plan

The SDK-container Ninja dry-run scheduled 21 actions, including native context
C and all affected C++ header consumers: VAAPI, RenderManager,
LinuxRendererGLES, DVBridgeGLES, RendererVAAPIGLES, VaapiEGL,
WinSystemGbmGLESContext, OptionalsReg, and PlatformLinux. Archive dependencies
and the final Kodi executable are included. No CMake regeneration was scheduled.

The actual final linker rule places `-flto=1` after all link libraries, overriding
the existing wrapper's `-flto=7` without changing unrelated compile flags.
The full build uses one Ninja job, one CPU, network disabled, a hard 4 GiB
memory limit and the same memory-plus-swap limit (no additional swap allowance).

## Actual full-build result

The actual 21-action build completed successfully (exit 0) in 352.774 seconds,
including the serial final LTO link. Its cgroup memory peak was 2,415,263,744
bytes under the 4 GiB cap. Every recorded memory event counter was zero;
current and peak swap were zero, and Docker reported OOMKilled=false.

The completed executable is 34,807,432 bytes with SHA256
`b06db596c9cec559d5ea8634b6bdedcec0cf43bd376cb9be73529dada60c5931`.
The existing SDK executable link flags include `-s`; no separate post-build
strip operation was introduced. These sources follow public checkpoint
`d6a5e65231` with the reviewed playback ABI 2 engine.

No installation or playback claim follows from build success. Successful
compiler/link gates do not prove the native path is selected for film playback,
that presentation continues, or that it meets real-time playback targets.
