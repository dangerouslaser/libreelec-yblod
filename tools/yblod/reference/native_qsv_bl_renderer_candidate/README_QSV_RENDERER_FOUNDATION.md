# QSV base-layer renderer foundation

This source-only draft accepts the separately published `CQsvMappedBuffer` through a borrowed VAAPI surface view. It does not masquerade as a VAAPI decoder-pool picture or relax that pool's decoder identity checks. The existing VAAPI import and cache bodies are identical after replacing picture fields with surface-view fields; their synchronization, EGL attributes, filters, and cache handling are unchanged.

The typed-buffer renderer factory requires both `DVBRIDGE_BASE_QSV=1` and `DVBRIDGE_NATIVE_RECONSTRUCTION=1`. Admission is limited to valid progressive P010 Dolby Vision frames, the expected VAAPI device/display, no crop, and zero rotation. This is not general 4K playback qualification. Metadata presence and bounded size alone do not prove resolved metadata semantics or correct frame association.

The typed route cannot use older reconstruction if native preparation fails. Ordinary missing enhancement frames or preroll rejection remain retryable; a false render result does not itself quarantine the buffer pool. Existing native engine uncertain-completion retention is unchanged.

## What is tested

The reproducible helper copies six SDK source files to disposable `/tmp`, applies the draft there, and never modifies the SDK. It runs five source-contract checks and compiles three objects with native support enabled and disabled under the SDK's actual compiler options plus `-Werror`. The combined run passed with a 388,759,552-byte memory peak, a 512 MiB limit, no swap, one CPU, no network, no GPU access, and zero memory events. The typed configuration branch retains the parent renderer's generic configuration-change check; that regression check is source-only, not a running Kodi geometry test.

Run on Ollie with the reviewed SDK image:

```sh
sh tools/yblod/reference/native_qsv_bl_renderer_candidate/check_qsv_renderer_candidate.sh /home/bryan/Projects/libreelec-yblod libreelec-dv-build:latest
```

These are compile/source tests, not EGL-import, decoder, playback, pixel, or performance tests. The mapped-buffer foundation's separate CPU ownership tests use a mocked hardware map.

## Remaining integration

The draft depends on adding the standalone buffer implementation to Kodi's buffer sources. No decoder currently creates this buffer. A separate default-off pre-open decoder path must select `hevc_qsv`, derive QSV from the actual VAAPI device, and require a genuine new FFmpeg Dolby metadata option before opening. That option and complete accepted-access-unit metadata association are not implemented here. A dedicated hardware decoder must retain its mapped-frame pool through drain/reset and choose QSV hardware frames without software fallback.

Combined Profile 7 packets must preserve their original identity for both decoders. Metadata admission must count only actual layer-zero VCL first slices, permit ignored enhancement-layer UNSPEC63 encapsulation, and follow native trailing-RPU selection semantics. This draft does not add a bitstream filter or claim that metadata association is solved.
