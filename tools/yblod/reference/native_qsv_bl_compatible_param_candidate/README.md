# Compatible QSV sequence-header warnings

This is an opt-in FFmpeg 9.0.2 source experiment, not a qualified Kodi playback build. It allows `MFX_WRN_VIDEO_PARAM_CHANGED` only after querying the decoder and confirming that its current parameters still match the owned progressive P010/10-bit 4:2:0 frame pool and existing allocation/crop. An incompatible change remains rejected. It does not reset the Dolby parser, replace tokens, or assume that any consumed bytes mean a complete picture was accepted.

`compatible-param-warning.patch` applies after the metadata foundation and required real-initialization fix in `../native_qsv_bl_ffmpeg_metadata_candidate/`. The included `qsvdec.c` is that complete combined source, with upstream copyright retained. `qsv_dovi.h` and the configuration overlay are included so the CPU fixture has no private source dependency. The decoder option remains `dovi_metadata=0` by default; unsupported builds reject an explicit request to enable it.

## Reproduce the CPU fixture

The recorded run used the locally cached immutable Docker image `sha256:33c6601e0e65d900edc712bdb6f40bb1e680669d5ffb76ecd014c8e6f2ec0e1e`. That image must already exist locally; this identifier is not a published registry download. It contains a C compiler, VPL/VA development libraries and FFmpeg 9.0.2 source with static `libavcodec.a` and `libavutil.a` at `/opt/ffmpeg-source`. The surrounding reference directory contains the FFmpeg build Dockerfile; independently rebuilding it is not proof of identical image contents and requires a fresh qualification record.

From this directory, on a Linux Docker host with cgroup v2:

```sh
python3 run_compatible_param_warning_fixed_cpu.py
```

No media, GPU, SDK replacement or environment variable is needed. The controller mounts this directory read-only, verifies the immutable image and a 512 MiB memory limit, zero swap, one CPU, no network and no GPU devices. It verifies four source hashes before compiling. A fresh `cpu-fixed-attempt/` directory and named container are required; existing attempts are deliberately not removed or reused. Results, logs and terminal container state are retained there. The controller has a 120-second deadline and stops only its owned container on failure or interruption.

## Evidence and limits

The actual candidate `qsv_decode` CPU fixture passed 53 cases, including ownership guards, incompatible parameters, query failures, partial consumption with the same prepared metadata/token, delayed output, reset and quarantine contracts. MFX submission, synchronization and dispatcher close are scripted mocks. Peak memory was 39,956,480 bytes, with zero memory events and swap.

Two prior fixture attempts are recorded in `COMPATIBLE_PARAM_CPU_RESULTS.json`: the added owned-session mock initially reached the real dispatcher close with a fake handle. An ASAN run identified that fixture gap; the correction explicitly mocks `MFXClose` and checks that the actual flush path closes it once. Product source was not changed to address that fixture failure.

This CPU evidence does not establish hardware acceptance, previous-RPU reference coverage, pixel accuracy, full parameter-change reconfiguration, Kodi playback, HDMI output or performance improvements. Changed allocation/crop still fails closed.

## Isolated hardware result

`COMPATIBLE_PARAM_BUILD_RESULTS.json` records a separate copied-source libavcodec build, with the original SDK and previous libraries unchanged. The container had a 4 GiB limit, zero swap, one CPU, no network or GPU, and serial compilation/LTO; peak memory was 584,028,160 bytes with zero memory events and swap. This report is build evidence, not playback evidence.

`COMPATIBLE_PARAM_HARDWARE_RESULTS.json` records one subsequent Ollie trial using that exact library and the preserved historical three-frame comparison probe. All nine raw P010 planes had literally zero sample differences; independently decoded native HEVC Dolby metadata, raw RPU bytes and frame properties matched. The live owned child, actual i915 client and mapped executable closure were verified. Only the three selected QSV frames were directly mapped to VAAPI; this is not a claim that every returned frame was mapped.

The initial simultaneous two-decoder trial exceeded its 512 MiB test cgroup and was retained as a failure. A separately authorized 1536 MiB diagnostic budget then passed with a 679,452,672-byte peak, zero memory events and zero swap. The larger allowance is not a Kodi memory optimization or a performance comparison. Both attempts are disclosed in the scalar report. No access-unit coverage, full reconfiguration, Kodi playback or physical HDMI output is qualified by this three-frame result.
