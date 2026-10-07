# QSV/VPL nearest-neighbour check on Petunia, 2026-10-06

These are synthetic P010 checks against exact 2x duplication, not film output or
comparison to licensed Dolby hardware. Kodi's installed runtime was not changed.

The existing VA-API scaler candidate built successfully (binary
9cda06190c4370df205d0868545da25a4bc7ab7ef964d806a81ca2c4936f013f),
but its nearest-neighbour pixel gate failed. It is not a qualified playback build.

Actual VPL testing used the same VPL dispatcher/runtime libraries as the
successful dual-QSV decode tests. The probe requests a hardware VA-API session,
P010 32x32 to 64x64, async depth one, and MFX_INTERPOLATION_NEAREST_NEIGHBOR=1.
It uploads/reads synthetic system-memory surfaces; production zero-copy video
surfaces, chroma-siting conversion and playback efficiency are not qualified.

| Request | Query / initialization | Exact-nearest pixel test |
| --- | --- | --- |
| Default scaling + nearest | Query -15 | Not submitted |
| Explicit VEBOX/media-engine scaling + nearest | Query 0, Init 0; GetVideoParam retained mode 1003 and interpolation 1 | 4,092/4,096 luma and 1,245/2,048 chroma words differed |
| Explicit VEBOX scaling + bilinear control | Query 0, Init 0; readback retained interpolation 2 | Same mismatch counts and same first 12 luma words as the nearest/VA-API observations |
| Explicit compute scaling + nearest | Query warning 5; returned scaling mode 0 instead of requested 1001 | Rejected before submission; no fallback accepted |

Output samples remained whole 10-bit codes, but did not produce exact nearest
duplication. Readback of the selected VPL option is not evidence that the scaler
honors that algorithm. The matching bilinear control supports an ignored-option
or runtime/hardware limitation interpretation; a specific internal driver cause
is not established. No claim is made about every Intel GPU or driver version.

The current P010 media-engine route cannot be called verified nearest-neighbour.
The next implementation must prove pixel behavior (and separately preserve the
required chroma phase), rather than silently accepting a successful API call.

All probes were bounded to 512 MiB, no swap, one CPU and a 30-second unit deadline.
No film data, raw layer exports, or Dolby payloads are included here.
