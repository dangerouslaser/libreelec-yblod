# Base-layer QSV Kodi integration candidate

This source-only candidate connects the previously published typed QSV-to-VAAPI buffer and renderer to Kodi's FFmpeg decoder. It is default OFF and has not been qualified with hardware decoding or playback.

`qsv-bl-kodi-integration-source-only.patch` contains the complete eleven-file Kodi change, including the earlier mapped-buffer and renderer foundations. Do not also apply those earlier Kodi patches. The smaller `qsv-bl-kodi-decoder-source-only.patch` is the three-file decoder/build-registration delta for an already integrated foundation.

## Admission and ownership

The route requires `DVBRIDGE_BASE_QSV=1`, `DVBRIDGE_NATIVE_RECONSTRUCTION=1`, HEVC Profile 7 with an enhancement layer, no forced software decoding and no rotation. It requires the new FFmpeg `hevc_qsv` Dolby metadata option before opening the codec. The published FFmpeg metadata candidate and its hardware format admission fix are both prerequisites.

One QSV device is derived from a retained VAAPI device on Kodi's renderer display. Format callbacks accept only QSV on that same device; FFmpeg rebuilds its frame pool without creating another device. Genuine returned frames enter the refcounted mapped-buffer pool before any software filters. Reset retires the pool generation while consumer-held frames retain their owners. Enhancement decoding receives the original VAAPI device, so its separate VAAPI/QSV selection is unchanged.

The typed renderer is native-only. Failed native preparation cannot use the older reconstruction route. Ordinary enhancement-layer preroll is not treated as uncertain GPU completion. The initial mapped-buffer gate still rejects crop, interlacing and unsupported geometry; actual coded-padding/crop admission is not qualified here.

The `DVBridge BL QSV` log records codec selection and successfully mapped frame counts. Its generation counter describes decoder pool-reset epochs, not proof of hardware completion or pixel correctness. Kodi reports this selected route as hardware decoding rather than incorrectly classifying it as software.

## Reproduce source checks

```sh
sh tools/yblod/reference/native_qsv_bl_kodi_integration_candidate/check_qsv_kodi_integration_candidate.sh /path/to/LibreELEC
```

The complete patch applies to disposable copies. Six decoder and five renderer source-contract checks pass; two strict SDK decoder objects compile with DVBridge enabled and disabled. The combined run peaked at 427,843,584 bytes under 512 MiB, no swap, one CPU, no network and no GPU. These checks do not execute Kodi codec opening, real hardware mapping or playback. Earlier mapped-buffer ownership tests remain separately scoped CPU fixtures.

## Isolated FFmpeg build

`check_isolated_qsv_bl_ffmpeg.sh` prepares a fresh private copy with the two exact reviewed FFmpeg patches. It defaults to a dry run; `--prepare` makes the copy, `--configure` checks configuration without make, and `--build` additionally builds it. The SDK is read-only, no install runs, and no SDK libraries are replaced. The pinned SDK container has 4 GiB RAM, no swap, one CPU, no network, no GPU, serial make and explicit serial LTO. Its source copy excludes compiled artifacts and is cleaned only inside the new private destination.

The first two private attempts failed at configure: first because the SDK assembler directory was absent from PATH, then because the target pkg-config environment was missing. Neither reached compilation or modified the SDK. The revised helper reproduces the original LibreELEC target environment without disabling assembly or dependencies. It verifies that every originally enabled configuration macro remains enabled. Build artifacts and any failure logs remain private; a build alone will not establish frame accuracy or runtime ownership.

The current isolated-build helper hashes are `b597bca85abbce183ae5f949d0a4d5f27b1b35e8b4de416b5df29bb91b8741ee` (Python) and `06321b6a2adab2ece9303fa0e9ba9758b50413dfe0f997822f795156de4ba1dd` (launcher). These identify reproduction code, not a successful build or playback result.

The remaining gates are actual native-HEVC versus QSV sample/metadata association, on-target owned mapping/reset/drain, movie frame equality, then playback measurements. The FFmpeg candidate currently rejects parameter changes safely; general graceful reinitialization remains separate work.
