# QSV Dolby metadata decoder candidate

This source-only FFmpeg 9.0.2 candidate adds `hevc_qsv -dovi_metadata 1` for restricted progressive P010 input. The option defaults to OFF. CPU tests exercise the actual decoder functions with mocked Intel runtime operations; they do not qualify hardware decoding, Kodi playback, picture accuracy or performance.

The patch includes the previously published GPL-3.0-or-later AU transaction component. The option requires a GPL/version3-enabled FFmpeg build; unsupported builds reject an ON request. The existing default-OFF path retains its original timestamp conversion, decoder retry and surface synchronization behavior.

## Frame association and retained ownership

Each prepared access unit receives a unique positive internal timestamp. Metadata state is deep-cloned before native Dolby parsing and published only when the actual MFX data offset accepts the complete access unit. Partial retries preserve the same prepared snapshot and token. Completed output is synchronized before its timestamp selects an immutable metadata snapshot; the original signed source timestamp and duration are then restored.

The input queue and accepted metadata together are bounded to 64 entries; queued and partially consumed encoded packets are bounded to 64 MiB. DEVICE_BUSY retries reuse the same surface within a five-second monotonic deadline. MORE_SURFACE retries may obtain at most 16 surfaces per call. These limits apply only with the new option enabled.

Opt-in initialization creates one stable heap owner before Intel registers allocator callbacks. A failed synchronization or unverified decoder close retains that same owner, including packet storage, surfaces, hardware-device references and allocator callback addresses. A process-wide terminal poison prevents repeated uncertain generations. Safe retirement synchronizes retained handles and requires a successful decoder close before releasing owners. The initial implementation rejects external decoder sessions.

The synchronization boundary follows Intel's requirement to [synchronize video-memory output before passing it to a non-VPL component](https://intel.github.io/libvpl/latest/programming_guide/VPL_prg_transcoding.html). Busy retry and successful close semantics are described in the [VideoDECODE API](https://intel.github.io/libvpl/latest/API_ref/VPL_func_vid_decode.html).

## Reproduce the CPU checks

Run from a host with the cached `yblod-ffmpeg9-decode:9.0.2` and `libreelec-dv-build:latest` images:

```sh
sudo sh tools/yblod/reference/native_qsv_bl_ffmpeg_metadata_candidate/check_qsv_dovi_decoder_candidate.sh /path/to/LibreELEC
```

The SDK path must contain `build.LibreELEC-Generic.x86_64-13.0-devel/build/ffmpeg-9.0.2`. The helper mounts it read-only, applies the patch to disposable copies under each container's `/tmp`, and performs five separate checks. Containers have 512 MiB RAM, no swap, one CPU, no network and no GPU device. Both precompile limits and final memory events are checked. No production source or configuration is modified.

## CPU qualification scope

The actual decoder fixture covers partial acceptance, delayed and reordered output, EAGAIN retention, unknown and duplicate tokens, packet queue limits, missing output at end of stream, verified reset, synchronization failures, close failures, retained input storage and bounded retries. A separate fixture registers the production allocator callbacks and invokes all five after releasing the original private context. Its dynamic-pool allocation case includes both rejected and valid external decode requests. Session creation and hardware operations remain mocked.

The strict object check uses the authoritative SDK compiler recipe. The configure smoke tests run the patched configure with only HEVC QSV selected, verifying that the new Dolby parser dependencies are selected in GPL/version3 builds and excluded without GPL. Source hashes and numeric resource results are recorded in `QSV_DOVI_DECODER_CANDIDATE_TEST_RESULTS.json`.

## Remaining integration and qualification

Parameter-change notifications currently reject the frame safely; graceful draining and reinitialization must preserve and resolve all old picture tokens before the next generation. Previous-RPU-reference inputs, real MFX timestamp behavior, hardware reset and allocator callbacks, actual QSV-to-VAAPI mapping, Kodi decoder selection and movie playback remain separate qualification steps. The published native-parser comparisons are CPU transaction equivalence checks, not Dolby conformance results.
