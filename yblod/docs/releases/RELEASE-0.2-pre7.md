# YBLOD 0.2-pre7 — GUI caching and asynchronous packing

Enables the GUI caches and bounded asynchronous packing tested on the Intel N150.
Unchanged GUI pixels reuse their colour calculations, and unchanged Home-screen
graphics reuse their rendered image. Movie-only packing can run ahead into the
other display buffer. When controls appear, their current contents take priority.
Reconstruction and packing arithmetic are unchanged.

## Measured improvements

Median CPU-side processing/wait totals, not total GPU time or display latency:

| Test | Before | After |
| --- | ---: | ---: |
| FEL with Home visible: caching | 100.75 ms | 15.37 ms |
| P8.4 with Home visible: caching | 93.02 ms | 15.56 ms |
| FEL clean playback: async packing | 13.49 ms | 10.71 ms |
| P8.4 clean playback: async packing | 11.29 ms | 8.86 ms |

These are separate comparisons, not additive gains. Twelve asynchronously packed
frames passed byte-exact checks against the existing packing oracle. Clean test
playback reported no drops/skips. A single GUI-transition skip occurred with async
both enabled and disabled. Full data and test limitations are in
`GUI-CACHE-20261010.txt` and `ASYNC-PACK-20261010.txt`.

## Testing scope and rollback

The GUI cache uses about 158 MiB of additional GPU-accessible memory at 4K.
The new paths are experimental: these tests do not qualify every profile, skin,
Intel device or 4K60 workload. Async packing runs ahead only without overlays.
All pre6 fixes remain included; the kernel and HDMI signalling are unchanged.

To disable the new paths, merge these entries into
`/storage/.config/native-dv.env` (preserve any existing settings), then restart Kodi:

```ini
DV_PRIVATE_ASYNC_PACK=0
DV_PRIVATE_GUI_CACHE_HOME=0
DV_OVERLAY_PIXEL_CACHE=0
```

Use the update `.tar` or fresh-install `.img.gz`. Attached manifests describe the
exact packaged-runtime validation and whether the release image was boot-tested.
