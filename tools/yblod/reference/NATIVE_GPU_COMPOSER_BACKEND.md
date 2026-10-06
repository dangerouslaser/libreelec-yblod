# Borrowed-texture integer composer

The isolated C API in `engine/experimental/native_gpu_composer_backend.h` now has an actual GPU image-output gate. It accepts five explicitly prepared normalized textures and canonical integer metadata in a caller-owned dedicated desktopGL context. It owns three reconstructed R16UI planes; it does not open files, create an EGL display, invent enhancement scaling/guide policy, or render colour.

Submission dispatches three full planes and inserts one frame fence. Completion reads a four-byte frame error flag. Fractional P010 input rejects the entire frame; valid unsupported metadata returns a distinct fallback status before GL mutation. Output/input reuse still requires the caller to synchronize consumers and restore its original EGL bindings before Kodi GLES rendering. The initial supported route is enabled 10-bit enhancement with whole P010 samples, output depth10 or12. Disabled enhancement and fractional Y416 are not silently converted into this route.

## Actual image-output checkpoint

[Public scalar result](results/native-gpu-composer-image-frame-checkpoint-20261005p.json) records two prepared4K frames. Each compares every final reconstructed code:12,441,600 values across three planes, against191 bounded CPU oracle subchunks. Both independent four-stage CPU preflights completed first. The GPU intermediate stages are not read back in this image gate; their separate exactness checkpoint remains available in the normalized texture diagnostic.

| Frame | Warm backend submit/finish wall time (ms) | New-input preparation/upload wall time (ms) |
|---|---|---|
|2296|17.943,17.175,16.855|30.471|
|1406|15.037,14.871,14.853|27.146|

Warm timings include three whole-plane dispatches, one completion wait and the four-byte error readback, but no reconstructed pixel readback. They exclude preparation/upload of a new frame. These are host timings, not isolated shader execution times or a sustained playback claim. This is diagnostic texture upload, not VAAPI zero-copy import. Peak memory256,376,832 bytes within a512MiB/no-swap cap; all memory events were zero. Kodi and pinned private inputs/runtime were unchanged; GL/EGL completion and cleanup passed.

## Next integration gates

Keep existing production fallback intact. Exercise declared enhancement scaling and guide preparation on live imported surfaces, retain frame/PTS/contract association, then expand12-bit reconstructed420 into RGBA32F YCC using the explicit bilinear-left diagnostic policy. Validate that expansion independently before connecting colour conversion and the desktopGL-to-GLES bridge. Measure new-frame end-to-end cost and sustained playback; resident-input warm timing alone does not answer those questions.

Host-only tests validate malformed-input precedence, metadata widths, fractional samples, file aliases, boundary tails and oracle structure. They do not prove GPU capabilities or image correctness; the separate actual GPU checkpoint does.
