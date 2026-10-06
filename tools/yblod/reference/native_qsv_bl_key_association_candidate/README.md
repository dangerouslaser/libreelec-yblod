# BL QSV picture KEY association candidate

This source-only correction preserves the strict frame comparison. A finite-window diagnostic found matching Dolby instructions, RPU bytes and other compared frame properties, but native HEVC marked a picture KEY and QSV did not.

Native FFmpeg treats HEVC NAL types 16–23 as IRAP/KEY. Stock QSV uses the MFX IDR flag. This candidate records the admitted picture's IRAP classification with its existing immutable timestamp token and restores only KEY on the corresponding returned frame. It does not infer KEY from an I-picture and does not change pixel math.

## Apply order

Start with the reviewed BL metadata decoder candidate and its real-init/surface-info correction, then apply the compatible-parameter warning candidate. Apply `hevc-qsv-dovi-key-association.patch` last. The supplied full `qsvdec.c` and `qsv_dovi.h` are the resulting source snapshot.

The change is restricted to `dovi_metadata=1`; default-OFF QSV retains its existing key assignment.

## CPU evidence

`run_key_cpu.py` runs the actual decoder-body fixture with scripted MFX operations, plus synthetic BLA/IDR/CRA and non-IRAP pictures. It requires the pinned cached FFmpeg fixture image and runs with 512 MiB, no swap, one CPU, no network or GPU. Run it from a fresh directory on a Docker host. Its first attempt passed the decoder fixture but failed linking the new standalone fixture; adding the already-used VPL/VA libraries fixed that helper-only error.

The additional native-parser fixture passed 10 admission checks, 382 transactions, 388 state comparisons, 378 parser-error cases and three reordered snapshots. Its real RPU input remains private. Strict SDK object compilation passed with the feature enabled and with GPL/version3 disabled. These are CPU regression checks, not Dolby conformance or hardware playback proof.

## Remaining qualification

Rebuild the isolated FFmpeg copy and rerun the unchanged strict finite-window hardware comparison before using this correction in Kodi. Prior-RPU reference semantics, graceful allocation/crop changes, typed mapped-buffer admission, full Kodi playback and performance remain separately qualified work. The geometry diagnostic describes one rejected pair, not all frames or an actual renderer admission result.
