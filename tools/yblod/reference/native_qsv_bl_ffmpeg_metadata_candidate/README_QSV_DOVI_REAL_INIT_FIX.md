# QSV Dolby metadata hardware format admission fix

This additive source-only patch corrects a hardware-output admission check in the CPU candidate. FFmpeg's actual `qsv_decode_init_context` stores the software format P010 in `avctx->pix_fmt`, even when hardware frames come from a QSV pool. Requiring that cached field to equal QSV would reject valid initialization. Apply `qsv-bl-metadata-source-only.patch` first, then `qsv-bl-metadata-real-init-fix.patch`; the original candidate alone is not ready for hardware testing.

The corrected gate verifies a progressive P010 decoder configuration, video-memory output and a typed QSV/P010 frame pool on the retained device. Each returned frame must itself have QSV format and an owned P010 QSV frame context on that same device before metadata is attached. Default-OFF behavior remains unchanged.

The opt-in path also copies the returned decoder surface Info to the actual QSV frame, rather than relying on the software-format cache for that update. This preserves runtime geometry and crop fields for the subsequent hardware-frame adapter.

## CPU checks

Ten cases execute the actual initialization body, then actual process/decode bodies, with Intel Init, decode, synchronization and allocation mocked. Valid initialization leaves the cache as P010 but returns a QSV frame with the correct timestamp and duration. Returned Info deliberately differs from the mocked pool prefill, including crop fields; the opt-in output preserves that returned Info, while the OFF control retains its existing behavior. Corrupted returned format, absent frame context, incorrect frame software format, foreign frame-device ownership and invalid input configurations are rejected. A held decoded-buffer reference survives verified decoder cleanup and frees once on final consumer release.

The original 24 decoder control cases now use typed mocked pools and refcounted frame contexts. They also pass against the corrected source, alongside the unsupported-GPL gate and strict authoritative SDK object compile. The previous CPU report records the original historical fixture hashes; the corrected source and fixture hashes are recorded in `QSV_DOVI_REAL_INIT_FIX_TEST_RESULTS.json`.

```sh
sudo sh tools/yblod/reference/native_qsv_bl_ffmpeg_metadata_candidate/check_qsv_dovi_real_init_candidate.sh /path/to/LibreELEC
```

The helper uses the two cached image IDs recorded in the scalar result, rather than mutable tags. It mounts the SDK read-only and patches disposable copies. Each container has 512 MiB RAM, no swap, one CPU, no network and no GPU. No production source is modified.

## Remaining qualification

These are CPU control-flow and ownership checks, not genuine hardware decoding or physical HDMI comparisons. Actual decoder allocation, previous-RPU-reference inputs, driver timestamp association, Kodi integration and playback remain unqualified. Graceful parameter-change draining is a separate source candidate; this fix retains the original safe parameter-change rejection.
