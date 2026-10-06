# Kodi BL and EL source timestamp checks

For the frozen combined Kodi candidate, a successful native output capture with `pts == el_pts` can verify exact decoded BL-to-EL source timestamp pairing for that rendered frame. It does not independently verify the player's presentation timestamp, scheduling, packet-duration forwarding or whole-playback pairing.

## Frozen source identity

References below are line numbers in the isolated Piers source used for the combined candidate, not moving upstream line numbers. Paths are relative to the Kodi source root; fingerprints are code hashes only.

| Source | SHA256 |
| --- | --- |
| `xbmc/cores/VideoPlayer/DVDCodecs/Video/DVDVideoCodecFFmpeg.cpp` | `be1387b8b9213bc8e35073c2ebae2bac04e785d488716f34b654d2aa85d53f2d` |
| `tools/dvbridge/dvbridge_fel.c` | `fed8e6e9c3eb4a53108cfe49778959c6df794a027aa646e57145d03a97803df1` |
| `xbmc/cores/VideoPlayer/VideoRenderers/LinuxRendererGLES.cpp` | `020561056c61948a03fecbe89b2ebb7a3d47beb5528aecc2f25132f6cdb3b5e3` |
| `xbmc/cores/VideoPlayer/VideoRenderers/HwDecRender/RendererVAAPIGLES.cpp` | `c8112cc8825ec93153558e2450bfffa1d0bf5431e5a40260ef68f8d3231b6978` |
| `xbmc/cores/VideoPlayer/VideoRenderers/DVBridgeGLES.cpp` | `6c9257a473803212afc38b16e520ff2772ea81a9b08c7b868705b6d34e6082f7` |
| `xbmc/cores/VideoPlayer/VideoRenderers/DVBridgeGLES.h` | `5281306718b8575d9d06b98817b398e1f7330ed33c9100695c858000cd931f0f` |
| `xbmc/cores/VideoPlayer/VideoPlayerVideo.cpp` | `ce1bcc4e3d1cb3660d1b8f9383b650032cc77b3246cbc2bf1c3ccff93337e9e9` |

## Timestamp path

`DVDVideoCodecFFmpeg.cpp:1474` assigns `VideoPicture.doviSourcePts` from the decoded frame's `best_effort_timestamp`. The FEL emitter rejects an unknown source timestamp at line 843 and calls `dvbridge_fel_take` with that exact integer at line 846. The helper restores a QSV EL frame's matched token timestamp into its `pts` and `best_effort_timestamp` at `dvbridge_fel.c:325`; its take operation returns a frame only when `candidate->pts == requested_pts` at line 573. It does not substitute a neighbouring frame.

`LinuxRendererGLES.cpp:291–293` copies `doviSourcePts` directly into the renderer's `doviPts` and `doviSourcePts`. This is important: renderer `doviPts` is not copied from the player's `VideoPicture.pts`. `RendererVAAPIGLES.cpp:299–300` forwards those two source fields into the layer. `DVBridgeGLES.h:41` declares the layer packet timebase as `1/AV_TIME_BASE`; `DVBridgeGLES.cpp:722–724` binds the decoded BL and returned EL timestamps into the native association. Lines 577–578 retain the admitted layer and enhancement timestamps for output capture; lines 1188–1192 write them as `frame.json` fields `pts` and `el_pts`.

Player presentation timing is a separate path. `DVDVideoCodecFFmpeg.cpp:1525–1538` derives `VideoPicture.pts` from best-effort time and can invalidate duplicate presentation timestamps. Its DTS uses input bookkeeping at lines 1521–1523, not `AVFrame.pkt_dts`. Source capture equality cannot prove that duplicate handling or player scheduling was correct.

## Minimal checks with the existing binary

For one explicitly controlled BL-QSV plus EL-QSV capture, bind all observations to the same verified Kodi child, binary and loaded runtime:

1. Require startup `decoder=hevc_qsv`, metadata enabled and async-depth readback 1. Require positive, increasing BL `mapped` counts in the same generation. These counts increment only after `GetMapped` and `GetPictureCommon` succeed (`DVDVideoCodecFFmpeg.cpp:1105–1127`). They prove actual mapping, not frame presentation.
2. Require native output capture and the existing direct/planar route expected for the test. The typed QSV renderer validates its mapped buffer, sets `nativeOnly`, and refuses old reconstruction fallback (`RendererVAAPIGLES.cpp:303–307`; `DVBridgeGLES.cpp:985–1000`). A successful native draw following the same generation's actual mapping therefore exercises typed admission naturally; merely selecting the option does not.
3. Require `el_decoder_qsv=1`, positive `el_qsv_map_sequence`, `el_qsv_native_used=1`, and exact source `pts == el_pts` in the associated output capture. Require the same-frame FEL residual evidence, not just an enhancement surface: the renderer sets FEL only when its resolved mapping has active NLQ (`DVBridgeGLES.cpp:524–536`).
4. Require no decoder/native/owner/cleanup failures, no fallback warnings, a stopped player and successful native shutdown. Check captured picture output against the separately retained baseline using the existing exact comparator; route and timestamp checks alone are not an image-accuracy proof.

These checks need no rebuild or new telemetry. They remain a captured-frame and short-runtime qualification. Full playback, flush/seek ownership inside Kodi, presentation scheduling, duration forwarding, previous-RPU references and changed allocation/crop handling require their own evidence.

## Remaining presentation diagnostic

The existing `DVBridge playback health` log reports downstream `pts_s` and `pts_valid` (`VideoPlayerVideo.cpp:897–906`), but not the decoded source timestamp or duplicate-invalidation decision. The player may replace unknown picture PTS with guessed time or DTS first (lines 718–725). Consequently, that log cannot alone establish source-to-presentation identity or prove that no timestamp fallback occurred.

A possible additive, default-off diagnostic is one sampled row in the FEL emitter immediately before `CopyRef` (`DVDVideoCodecFFmpeg.cpp:875`). For native BL QSV, it could record the current generation, mapped-frame count, source timestamp, retained decoded best-effort timestamp, player `VideoPicture.pts`, known/duplicate-invalid flags, and exact matched EL timestamp. Retain the best-effort value or duplicate decision explicitly when `GetPictureCommon` computes them; do not infer duplicate handling merely from an unknown presentation timestamp. Bound reporting to the first three frames and every 120th frame, with a fixed maximum of 64 rows per generation. A same-frame sequence could correlate those rows to capture output without exporting pixels, Dolby bytes or content hashes.

This is a proposal only. No diagnostic was added and no rebuild is required for the source-pair checks above. A sampled diagnostic would qualify sampled presentation ingress, not every displayed frame; full playback claims would additionally require bounded aggregate unknown/fallback/duplicate counters and clean lifecycle identity.
