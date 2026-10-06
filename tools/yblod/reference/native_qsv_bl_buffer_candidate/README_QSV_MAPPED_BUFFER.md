# QSV base layer mapped buffer foundation

This standalone candidate owns hardware frames mapped from QSV to VAAPI and exposes a distinct Kodi video-buffer type. It is not connected to a decoder or renderer and cannot enable QSV base-layer playback. Existing VAAPI pool admission is unchanged.

The bounded pool has 32 slots. Reset invalidates a generation without freeing buffers still held by consumers. Mapping started before reset cannot join the new generation. Quarantine deliberately retains the pool and its owned frames permanently because consumer completion is uncertain; a future decoder must become terminal rather than repeatedly create replacement pools after quarantine.

Admission requires a direct QSV-to-VAAPI mapping, matching child-device identity and VA display, P010, progressive uncropped frames, bounded dimensions and a present bounded-size Dolby metadata block. Metadata presence is not semantic validation. Fully resolved per-frame Dolby instructions require the separate FFmpeg association implementation and native engine validation. Actual coded padding and crop behavior of movie frames remains untested.

Run `check_qsv_bl_mapped_buffer.sh` with an existing LibreELEC SDK project path and Docker access. The helper uses the SDK's actual Kodi compile-command flags and installed FFmpeg library, with a 512 MiB cap, no additional swap, one CPU, no network and no GPU mounts. It compiles the standalone source and runs a fixture using Kodi's actual `CVideoBuffer` reference-count implementation and real FFmpeg frame/buffer references. Hardware mapping is mocked. The mock retains a device buffer reference but uses a borrowed synthetic device context; it does not qualify real QSV session/device ownership.

Tests cover map failures and missing mapped-frame context, missing metadata, display mismatch, reset during mapping, retired in-use buffers, capacity, source-frame release before consumer release, device-buffer reference retention and terminal quarantine. No actual hardware map, renderer, decoder, picture accuracy or playback is qualified.
